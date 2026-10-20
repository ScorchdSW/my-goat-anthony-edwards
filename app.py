"""SportsEdge 2.3 — NBA milestone explorer with relative lower-risk and upside picks."""

from datetime import datetime, timedelta, timezone
import math

from zoneinfo import ZoneInfo

import pandas as pd

import requests
import re

import streamlit as st

from nba_api.stats.endpoints import commonteamroster, playergamelog, commonplayerinfo

from nba_api.stats.static import teams as nba_teams



st.set_page_config(page_title="My GOAT Anthony Edwards", page_icon="🏀", layout="wide")

st.markdown('''<style>.block-container{padding-top:1.5rem;max-width:1250px}div[data-testid="stMetric"]{background:#172238;border:1px solid #42526b;border-radius:12px;padding:12px}div[data-testid="stMetric"] label,div[data-testid="stMetric"] [data-testid="stMetricLabel"],div[data-testid="stMetric"] [data-testid="stMetricValue"],div[data-testid="stMetric"] [data-testid="stMetricValue"] *{color:#f8fafc!important;opacity:1!important}div[data-testid="stMetric"] [data-testid="stMetricLabel"]{color:#cbd5e1!important}</style>''', unsafe_allow_html=True)

MEL = ZoneInfo("Australia/Melbourne")

TEAM_LIST = nba_teams.get_teams()

TEAMS = {t['id']: t for t in TEAM_LIST}

BY_NAME = {t['full_name'].lower():t for t in TEAM_LIST}

STATS = {'Points':'PTS','Rebounds':'REB','Assists':'AST','3-pointers':'FG3M','Steals':'STL','Blocks':'BLK','Turnovers':'TOV','Points + Rebounds':'PR','Points + Assists':'PA','Rebounds + Assists':'RA','Points + Rebounds + Assists':'PRA','Double-double':'DD','Triple-double':'TD'}

THRESHOLDS = {'Points':list(range(5,51,5)),'Rebounds':list(range(2,21,2)),'Assists':list(range(2,21,2)),'3-pointers':list(range(1,11)),'Steals':list(range(1,7)),'Blocks':list(range(1,7)),'Turnovers':list(range(1,9)),'Points + Rebounds':list(range(10,66,5)),'Points + Assists':list(range(10,66,5)),'Rebounds + Assists':list(range(5,41,5)),'Points + Rebounds + Assists':list(range(10,81,5)),'Double-double':[1],'Triple-double':[1]}





def season_for(dt):

    y=dt.year if dt.month>=10 else dt.year-1

    return f'{y}-{str((y+1)%100).zfill(2)}'



@st.cache_data(ttl=1800, show_spinner=False)
def upcoming_games():
    """Fetch ESPN NBA fixtures for the next 8 Melbourne calendar days."""
    now = datetime.now(timezone.utc)
    start = now.astimezone(MEL).date()
    games = {}
    errors = []
    successful_days = 0
    # ESPN abbreviations sometimes differ from nba_api abbreviations.
    espn_abbreviations = {'NY': 'NYK', 'GS': 'GSW', 'SA': 'SAS', 'NO': 'NOP', 'UTAH': 'UTA'}
    by_abbr = {t['abbreviation'].upper(): t for t in TEAM_LIST}
    for offset in range(9):
        day = start + timedelta(days=offset)
        try:
            response = requests.get(
                'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
                params={'dates': day.strftime('%Y%m%d')},
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                timeout=5,
            )
            response.raise_for_status()
            events = response.json().get('events', [])
            successful_days += 1
        except (requests.RequestException, ValueError) as exc:
            errors.append(f'{day}: {exc}')
            continue
        for event in events:
            try:
                when = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
                if not now - timedelta(hours=3) <= when <= now + timedelta(days=9):
                    continue
                competitors = event['competitions'][0]['competitors']
                home_data = next(c['team'] for c in competitors if c['homeAway'] == 'home')
                away_data = next(c['team'] for c in competitors if c['homeAway'] == 'away')
                def find_team(data):
                    name = data.get('displayName', '').lower()
                    abbr = data.get('abbreviation', '').upper()
                    return BY_NAME.get(name) or by_abbr.get(espn_abbreviations.get(abbr, abbr))
                home_team, away_team = find_team(home_data), find_team(away_data)
                if home_team is None or away_team is None:
                    continue
                games[str(event['id'])] = {
                    'id': str(event['id']), 'when': when,
                    'home_id': home_team['id'], 'away_id': away_team['id'],
                }
            except (KeyError, IndexError, StopIteration, TypeError, ValueError):
                continue
    if not games and errors:
        raise RuntimeError('No games could be loaded. ESPN request issue: ' + errors[0])
    if not games and successful_days == 0:
        raise RuntimeError('ESPN did not return any successful schedule responses.')
    return sorted(games.values(), key=lambda x: x['when'])


@st.cache_data(ttl=86400,show_spinner=False)

def roster(team_id,season):

    df=commonteamroster.CommonTeamRoster(team_id=team_id,season=season,timeout=25).get_data_frames()[0]

    return df[['PLAYER_ID','PLAYER']].drop_duplicates().sort_values('PLAYER')



@st.cache_data(ttl=10800,show_spinner=False)

def season_games(player_id,season):

    return playergamelog.PlayerGameLog(player_id=player_id,season=season,timeout=25).get_data_frames()[0]



@st.cache_data(ttl=10800,show_spinner=False)

def player_history(player_id,season,number_seasons=5):

    start=int(season[:4]);parts=[]

    for y in range(start,start-number_seasons,-1):

        s=f'{y}-{str((y+1)%100).zfill(2)}'

        try:

            part=season_games(player_id,s)

            if not part.empty:parts.append(part)

        except Exception:

            continue

    if not parts:return pd.DataFrame()

    df=pd.concat(parts,ignore_index=True)

    df['GAME_DATE']=pd.to_datetime(df['GAME_DATE'],errors='coerce')

    df=df.dropna(subset=['GAME_DATE']).sort_values('GAME_DATE',ascending=False).drop_duplicates(subset=['Game_ID'],keep='first') if 'Game_ID' in df else df.sort_values('GAME_DATE',ascending=False)

    for col in ['PTS','REB','AST','FG3M','STL','BLK','TOV','MIN','FGM','FGA','FG3A','FTM','FTA']:

        df[col]=pd.to_numeric(df[col],errors='coerce') if col in df else 0

    df['PR']=df.PTS+df.REB;df['PA']=df.PTS+df.AST;df['RA']=df.REB+df.AST;df['PRA']=df.PTS+df.REB+df.AST

    doubles=(df[['PTS','REB','AST','STL','BLK']]>=10).sum(axis=1)

    df['DD']=(doubles>=2).astype(int);df['TD']=(doubles>=3).astype(int)

    df['FG%']=df.FGM.div(df.FGA.replace(0,float('nan'))).mul(100)

    df['3PT%']=df.FG3M.div(df.FG3A.replace(0,float('nan'))).mul(100)

    df['FT%']=df.FTM.div(df.FTA.replace(0,float('nan'))).mul(100)

    return df





def milestones(df,stat):

    col=STATS[stat]

    if df.empty:return pd.DataFrame()

    rows=[]

    for threshold in THRESHOLDS[stat]:

        hits=int((df[col]>=threshold).sum());n=len(df)

        rows.append({'Milestone':('Double-double' if stat=='Double-double' else 'Triple-double' if stat=='Triple-double' else f'{threshold}+ {stat}'),'Hit rate':f'{hits}/{n}','Hit %':round(hits/n*100),'Average':round(float(df[col].mean()),1)})

    return pd.DataFrame(rows)





def opponent_games(full, abbreviation):
    # Match the opponent abbreviation as a literal suffix, not a loose substring.
    pattern = r'(?:vs\.\s*|@\s*)' + re.escape(str(abbreviation)) + r'$'
    return full[full.MATCHUP.astype(str).str.contains(pattern, regex=True, case=False, na=False)]


@st.cache_data(ttl=86400, show_spinner=False)
def player_age(player_id):
    """Get NBA.com birth date; safely skip age adjustment if unavailable."""
    try:
        df = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=12).get_data_frames()[0]
        birth = pd.to_datetime(df.iloc[0].get('BIRTHDATE'), errors='coerce', utc=True)
        if pd.isna(birth):
            return None
        today = datetime.now(timezone.utc).date()
        return round((today - birth.date()).days / 365.2425, 1)
    except Exception:
        return None


def model_predictions(full, opponent, stat, age=None):
    """Experimental trend-aware model; outputs are uncalibrated estimates."""
    col = STATS[stat]
    sample = full.head(40).copy()
    if len(sample) < 5:
        return pd.DataFrame(), 'At least five previous games are needed for an estimate.'
    recent = sample.head(10)
    matchups = opponent_games(full, opponent).head(5)
    values = pd.to_numeric(sample[col], errors='coerce').fillna(0).to_numpy(dtype=float)
    weights = [0.96 ** i for i in range(len(values))]
    weighted_mean = sum(v*w for v,w in zip(values, weights)) / sum(weights)
    weighted_var = sum(w*(v-weighted_mean)**2 for v,w in zip(values,weights)) / sum(weights)

    # Detect sustained improvement/decline from non-overlapping periods.
    # Per-minute rates distinguish efficiency gains from simply playing longer.
    recent5 = sample.head(5)
    prior = sample.iloc[5:25]
    def per36(frame):
        minutes = pd.to_numeric(frame['MIN'], errors='coerce').fillna(0).sum()
        return float(pd.to_numeric(frame[col], errors='coerce').fillna(0).sum()) / minutes * 36 if minutes > 0 else None

    recent_rate, prior_rate = per36(recent5), per36(prior)
    trend = 0.0
    if col not in ('DD', 'TD') and len(prior) >= 10 and recent_rate is not None and prior_rate and prior_rate > 0:
        raw = (recent_rate / prior_rate) - 1
        # Confirm the direction using the last ten vs the previous 10-20 games.
        recent10_rate = per36(sample.head(10))
        older_rate = per36(sample.iloc[10:30])
        if recent10_rate is not None and older_rate and older_rate > 0:
            confirmed = (recent10_rate / older_rate) - 1
            if raw * confirmed > 0:
                trend = max(-0.12, min(0.12, 0.6 * confirmed + 0.4 * raw))
            else:
                trend = max(-0.035, min(0.035, 0.25 * raw))
        else:
            trend = max(-0.04, min(0.04, 0.25 * raw))

    # Age modifies confidence in a measured trend; it does not invent one.
    # Without age data, the trend is still used unchanged.
    age_factor = 1.0
    if age is not None and age < 24 and trend > 0:
        age_factor = 1.10
    elif age is not None and age >= 33 and trend > 0:
        age_factor = 0.85
    trend = max(-0.12, min(0.12, trend * age_factor))

    # Opponent-specific history, shrinking strongly when there are few meetings.
    opp_weight = min(0.25, len(matchups) / (len(matchups) + 15))
    opp_mean = float(matchups[col].mean()) if len(matchups) else weighted_mean
    mean = (1-opp_weight)*weighted_mean + opp_weight*opp_mean
    last5_min = float(recent5['MIN'].mean())
    base_min = float(sample['MIN'].mean())
    minutes_factor = max(0.85, min(1.15, last5_min/base_min)) if base_min > 0 else 1.0
    if col not in ('DD','TD'):
        mean *= (1 + trend) * minutes_factor

    variance = max(weighted_var, max(mean, 0) * 0.85, 1.0)
    sd = math.sqrt(variance)
    rows=[]
    for threshold in THRESHOLDS[stat]:
        if col in ('DD','TD'):
            successes = int((sample[col] >= 1).sum())
            probability = (successes + 1) / (len(sample) + 2)
            if len(matchups):
                opp_successes = int((matchups[col] >= 1).sum())
                opp_probability = (opp_successes + 1) / (len(matchups) + 2)
                probability = (1-opp_weight)*probability + opp_weight*opp_probability
        else:
            z = (threshold - 0.5 - mean) / sd
            probability = 0.5 * math.erfc(z / math.sqrt(2))
        probability = max(0.0, min(1.0, probability))
        label = stat if col in ('DD','TD') else f'{threshold}+ {stat}'
        rows.append({'Milestone': label, 'Model estimate': f'{probability*100:.0f}%',
                     'Last 10 hits': f'{int((recent[col]>=threshold).sum())}/{len(recent)}',
                     'Vs opponent hits': f'{int((matchups[col]>=threshold).sum())}/{len(matchups)}' if len(matchups) else 'No history',
                     'Projected average': round(mean,1) if col not in ('DD','TD') else '—'})
    trend_label = 'rising' if trend > 0.025 else 'falling' if trend < -0.025 else 'stable'
    age_label = f'{age:.1f} years' if age is not None else 'unavailable'
    description = (f'Form trend: {trend_label} ({trend:+.1%} adjustment); age: {age_label}. '
                   f'Opponent history: {len(matchups)} games against {opponent} '
                   f'(average {opp_mean:.1f} {stat.lower()} when available). '
                   f'Minutes factor: {minutes_factor:.2f}x. Up to {len(sample)} recent games analysed. '
                   'Estimates are not calibrated or backtested.')
    return pd.DataFrame(rows), description


def milestone_shortlist(prediction, full, stat):
    """Rank relative lower-risk and upside milestones; not betting advice or calibrated odds."""
    if prediction.empty:
        return pd.DataFrame(), pd.DataFrame()
    col = STATS[stat]
    recent = full.head(40)
    average = float(pd.to_numeric(recent[col], errors='coerce').mean())
    rows = []
    for threshold, item in zip(THRESHOLDS[stat], prediction.to_dict('records')):
        p = float(str(item['Model estimate']).rstrip('%')) / 100
        recent_hit = int((pd.to_numeric(recent.head(10)[col], errors='coerce') >= threshold).sum())
        rows.append({'Milestone': item['Milestone'], 'Threshold': threshold,
                     'Estimate': p, 'Model estimate': item['Model estimate'],
                     'Last 10': f'{recent_hit}/{min(10,len(recent))}',
                     'Vs opponent': item['Vs opponent hits'],
                     'Typical output': round(average, 1),
                     'Above typical': round(threshold / max(average, 0.1), 2)})
    if col in ('DD', 'TD'):
        safer = [r for r in rows if r['Estimate'] >= .7]
        return pd.DataFrame(safer), pd.DataFrame()
    # A relatively attainable milestone, not a guaranteed or 'safe' wager.
    safer = sorted([r for r in rows if r['Estimate'] >= .70],
                   key=lambda r: (r['Threshold'], r['Estimate']), reverse=True)[:3]
    # Unusually high output with a non-negligible model chance.
    upside = [r for r in rows if r['Above typical'] >= 1.35 and .08 <= r['Estimate'] <= .45]
    upside = sorted(upside, key=lambda r: (r['Estimate'], r['Above typical']), reverse=True)[:5]
    columns = ['Milestone', 'Model estimate', 'Last 10', 'Vs opponent', 'Typical output']
    return pd.DataFrame(safer)[columns] if safer else pd.DataFrame(), \
           pd.DataFrame(upside)[columns + ['Above typical']] if upside else pd.DataFrame()


def history_table(df):

    cols=['GAME_DATE','MATCHUP','MIN','PTS','REB','AST','FG3M','STL','BLK','TOV','FG%','3PT%','FT%']

    d=df[[c for c in cols if c in df.columns]].copy()

    if 'GAME_DATE' in d:d['GAME_DATE']=d.GAME_DATE.dt.strftime('%d %b %Y')

    return d.rename(columns={'GAME_DATE':'Date','MATCHUP':'Opponent','FG3M':'3PM','MIN':'Minutes'})



st.title('🏀 My GOAT Anthony Edwards')

st.caption('NBA milestone explorer · Melbourne time · Shareable dashboard · No bookmaker API required')

st.info('SportsEdge now includes **experimental mathematical estimates** as well as historical hit rates. Estimates are not backtested or calibrated, and are not betting advice.')



try:

    with st.spinner("Loading upcoming NBA games from ESPN (this can take a few seconds)..."):
        games=upcoming_games()

except Exception as exc:

    st.error(f'Could not load the NBA schedule right now: {exc}')

    st.info('The alternate ESPN schedule service may be temporarily unavailable. Try refreshing later.')

    st.stop()

if not games:

    st.warning('No upcoming NBA games were returned for the next 9 days. Check the schedule again later.')

    st.stop()



def game_label(g):

    home=TEAMS.get(g['home_id'],{}).get('full_name','Home team')

    away=TEAMS.get(g['away_id'],{}).get('full_name','Away team')

    return f"{away} @ {home} · {g['when'].astimezone(MEL).strftime('%a %d %b, %I:%M %p')}"



st.subheader('1 · Choose an upcoming game')

game_idx=st.selectbox('Game',range(len(games)),format_func=lambda i:game_label(games[i]))

game=games[game_idx];season=season_for(game['when'].astimezone(MEL))

home=TEAMS.get(game['home_id'],{});away=TEAMS.get(game['away_id'],{})



st.subheader('2 · Players from both teams')

st.caption('Load team rosters once, then select any player. Rosters may include injured or inactive players; availability is not yet verified.')

if st.button('🏀 Load players for this game',type='primary'):

    st.session_state['loaded_game']=game['id']

if st.session_state.get('loaded_game')!=game['id']:

    st.info('Click **Load players for this game** to begin.');st.stop()

try:

    with st.spinner('Loading both NBA rosters...'):

        a=roster(game['away_id'],season).assign(Team=away.get('full_name','Away'),Opponent=home.get('abbreviation',''))

        h=roster(game['home_id'],season).assign(Team=home.get('full_name','Home'),Opponent=away.get('abbreviation',''))

        roster_df=pd.concat([a,h],ignore_index=True)

except Exception as exc:

    st.error(f'Could not load rosters: {exc}. This can happen if NBA.com is temporarily blocking requests.');st.stop()



# Team-by-team leaders for the selected matchup. Scan is explicit to avoid
# dozens of slow NBA.com requests on every game-selection rerun.
st.subheader('🎯 Game prediction leaders · Points, Assists, Blocks, Rebounds, Steals & 3-Pointers')
st.caption('Top projected player on each team for each category. The milestone shown is the available threshold closest to (but not above) the projected average. Percentages are experimental and uncalibrated.')
leader_key = (game['id'], season)
if st.button('🧠 Calculate leaders for both teams', key='game_leader_scan'):
    leader_rows = []
    upside_rows = []
    scan_errors = []
    bar = st.progress(0, text='Calculating game leaders...')
    total = len(roster_df)
    for idx, player in enumerate(roster_df.itertuples()):
        try:
            history = player_history(int(player.PLAYER_ID), season)
            if len(history) >= 5:
                for category in ('Points', 'Assists', 'Blocks', '3-pointers', 'Rebounds', 'Steals'):
                    estimates, _ = model_predictions(history, str(player.Opponent), category)
                    if estimates.empty:
                        continue
                    # Scan unusually high milestones across BOTH teams, using the
                    # same trend/opponent-aware model as the player detail page.
                    _, upside = milestone_shortlist(estimates, history, category)
                    if not upside.empty:
                        for pick in upside.to_dict('records'):
                            chance = float(str(pick['Model estimate']).rstrip('%')) / 100
                            upside_rows.append({
                                'Team': player.Team, 'Player': player.PLAYER,
                                'Category': category, 'Milestone': pick['Milestone'],
                                'Model chance': pick['Model estimate'],
                                'Probability': chance,
                                'Above typical': pick['Above typical'],
                                'Typical output': pick['Typical output'],
                                'Vs opponent': pick['Vs opponent'],
                            })
                    projected = float(estimates['Projected average'].iloc[0])
                    thresholds = THRESHOLDS[category]
                    eligible = [v for v in thresholds if v <= projected]
                    target = max(eligible) if eligible else min(thresholds)
                    row = estimates.iloc[thresholds.index(target)]
                    leader_rows.append({
                        'Team': player.Team, 'Category': category,
                        'Player': player.PLAYER, 'Projected': projected,
                        'Milestone': row['Milestone'],
                        'Model chance': row['Model estimate'],
                        'Vs opponent': row['Vs opponent hits'],
                    })
        except Exception as exc:
            scan_errors.append(f'{player.PLAYER}: {str(exc)[:70]}')
        bar.progress((idx + 1) / total, text=f'Analysed {idx + 1} of {total} players')
    st.session_state['game_leaders'] = (leader_key, pd.DataFrame(leader_rows), pd.DataFrame(upside_rows), scan_errors)
    bar.empty()

saved_leaders = st.session_state.get('game_leaders')
if saved_leaders and saved_leaders[0] == leader_key:
    _, all_leaders, all_upside, scan_errors = saved_leaders
    if not all_leaders.empty:
        for team_name in (away.get('full_name', 'Away'), home.get('full_name', 'Home')):
            st.markdown(f'**{team_name}**')
            team_rows = []
            for category in ('Points', 'Assists', 'Blocks', 'Rebounds', 'Steals', '3-pointers'):
                options = all_leaders[(all_leaders['Team'] == team_name) & (all_leaders['Category'] == category)]
                if not options.empty:
                    team_rows.append(options.sort_values('Projected', ascending=False).iloc[0].to_dict())
            if team_rows:
                st.dataframe(pd.DataFrame(team_rows)[['Category', 'Player', 'Projected', 'Milestone', 'Model chance', 'Vs opponent']],
                             hide_index=True, use_container_width=True)
            else:
                st.info('Not enough player data for this team.')
    else:
        st.warning('No predictions could be calculated. NBA.com may be rate-limiting requests.')
    st.markdown('### 🚀 Top 4 higher-upside opportunities · Both teams')
    st.caption('The four most likely unusually high milestones from the players analysed. Each target is at least 35% above that player’s recent average, with a model estimate between 8% and 45%. These are NOT safe or proven profitable bets.')
    if not all_upside.empty:
        # Avoid filling the top four with multiple thresholds for one player;
        # show the strongest qualifying milestone for each player/category first.
        ranked = all_upside.sort_values(['Probability', 'Above typical'], ascending=[False, False])
        ranked = ranked.drop_duplicates(subset=['Player', 'Category'], keep='first').head(4)
        st.dataframe(ranked[['Team', 'Player', 'Category', 'Milestone', 'Model chance', 'Above typical', 'Typical output', 'Vs opponent']],
                     hide_index=True, use_container_width=True,
                     column_config={'Above typical': st.column_config.NumberColumn('× usual output', format='%.2fx')})
    else:
        st.info('No higher-upside milestones met the criteria among the players analysed.')
    if scan_errors:
        st.caption(f'{len(scan_errors)} players could not be analysed. Results may be incomplete.')
else:
    st.info('Click **Calculate leaders for both teams** once to see the twelve game leaders and top four higher-upside milestones. They stay visible while you explore this game.')

all_tab,player_tab=st.tabs(['👥 All-player overview','🔎 Player details'])

with all_tab:

    st.markdown('**Compare players across the selected game**')

    st.caption('To avoid overwhelming NBA.com with requests, load a small batch at a time. More players can be loaded in later batches.')

    left,right=st.columns([2,1])

    with left:focus=st.selectbox('Milestone category',list(STATS),key='overview_stat')

    with right:batch=st.selectbox('Players per batch',[3,5,10],index=1)

    choices=[f"{r.PLAYER} · {r.Team}" for r in roster_df.itertuples()]

    start=st.selectbox('Roster batch',list(range(0,len(roster_df),batch)),format_func=lambda i:f'{i+1}–{min(i+batch,len(roster_df))} of {len(roster_df)} players')

    if st.button('📊 Analyse this batch',key='batch_button'):

        records=[];failures=[]

        subset=roster_df.iloc[start:start+batch]

        progress=st.progress(0)

        for n,r in enumerate(subset.itertuples()):

            try:

                hist=player_history(int(r.PLAYER_ID),season).head(10)

                if not hist.empty:

                    ms=milestones(hist,focus)

                    for m in ms.to_dict('records'):

                        records.append({'Player':r.PLAYER,'Team':r.Team,**m,'Games':len(hist)})

            except Exception as exc:failures.append(f'{r.PLAYER}: {str(exc)[:100]}')

            progress.progress((n+1)/len(subset))

        st.session_state['overview_result']=(game['id'],focus,start,batch,pd.DataFrame(records),failures)

    result=st.session_state.get('overview_result')

    if result and result[:4]==(game['id'],focus,start,batch):

        _,_,_,_,table,failures=result

        if not table.empty:

            st.dataframe(table.sort_values(['Hit %','Games'],ascending=False),hide_index=True,use_container_width=True,height=420)

            st.caption('Ranking is by observed hit rate only. A 100% hit rate over a few games is not a 100% future probability.')

        else:st.warning('No player game logs were returned for this batch.')

        if failures:st.warning('Some players could not be loaded: '+'; '.join(failures))



with player_tab:

    selected=st.selectbox('Choose player',list(range(len(roster_df))),format_func=lambda i:choices[i])

    p=roster_df.iloc[selected]

    if st.button('📈 Load player analysis',type='primary'):

        st.session_state['detail_id']=(game['id'],int(p.PLAYER_ID))

    if st.session_state.get('detail_id')!=(game['id'],int(p.PLAYER_ID)):

        st.info('Select a player and click **Load player analysis**.')

    else:

        try:

            with st.spinner('Finding recent games, including previous seasons...'):

                full=player_history(int(p.PLAYER_ID),season)

        except Exception as exc:

            st.error(f'Could not retrieve game logs: {exc}');st.stop()

        if full.empty:

            st.warning('No historical NBA games were found for this player.');st.stop()

        recent=full.head(10)

        st.markdown(f"### {p.PLAYER} · {p.Team}")

        st.caption(f'{len(recent)} most recent available regular-season games · automatically crosses seasons · last five seasons searched')

        a,b,c,d=st.columns(4)

        a.metric('Points / game',f'{recent.PTS.mean():.1f}')

        b.metric('Rebounds / game',f'{recent.REB.mean():.1f}')

        c.metric('Assists / game',f'{recent.AST.mean():.1f}')

        d.metric('Minutes / game',f'{recent.MIN.mean():.1f}')

        a,b,c=st.columns(3)

        a.metric('FG%',f'{recent.FGM.sum()/recent.FGA.sum()*100:.1f}%' if recent.FGA.sum()>0 else '—')

        b.metric('3PT%',f'{recent.FG3M.sum()/recent.FG3A.sum()*100:.1f}%' if recent.FG3A.sum()>0 else '—')

        c.metric('FT%',f'{recent.FTM.sum()/recent.FTA.sum()*100:.1f}%' if recent.FTA.sum()>0 else '—')

        recent_tab,opp_tab,predict_tab=st.tabs(['📈 Last 10 games & milestones','🆚 Against this opponent','🧠 Experimental predictions'])

        with recent_tab:

            category=st.selectbox('Statistic',list(STATS),key='detail_stat')

            st.dataframe(milestones(recent,category),hide_index=True,use_container_width=True)

            if category not in ('Double-double','Triple-double'):

                chart=recent[['GAME_DATE',STATS[category]]].sort_values('GAME_DATE').set_index('GAME_DATE')

                st.bar_chart(chart,y=STATS[category])

            with st.expander('See individual game results'):

                st.dataframe(history_table(recent),hide_index=True,use_container_width=True)

        with opp_tab:

            opponent=str(p.Opponent)

            # MATCHUP is formatted like 'BOS vs. NYK' or 'BOS @ NYK'.

            matches=opponent_games(full, opponent)

            st.markdown(f'**Against {opponent}**')

            if matches.empty:

                st.info('No games against this opponent were found in the available five-season history.')

            else:

                last5=matches.head(5)

                st.caption(f'Last {len(last5)} of {len(matches)} available games against this opponent')

                x,y,z=st.columns(3)

                x.metric('Points / game',f'{last5.PTS.mean():.1f}')

                y.metric('Rebounds / game',f'{last5.REB.mean():.1f}')

                z.metric('Assists / game',f'{last5.AST.mean():.1f}')

                x,y,z=st.columns(3)

                x.metric('FG%',f'{last5.FGM.sum()/last5.FGA.sum()*100:.1f}%' if last5.FGA.sum()>0 else '—')

                y.metric('3PT%',f'{last5.FG3M.sum()/last5.FG3A.sum()*100:.1f}%' if last5.FG3A.sum()>0 else '—')

                z.metric('FT%',f'{last5.FTM.sum()/last5.FTA.sum()*100:.1f}%' if last5.FTA.sum()>0 else '—')

                opp_stat=st.selectbox('Opponent milestone category',list(STATS),key='opp_stat')

                st.dataframe(milestones(last5,opp_stat),hide_index=True,use_container_width=True)

                st.dataframe(history_table(last5),hide_index=True,use_container_width=True)

                with st.expander('All available games against this opponent'):

                    st.dataframe(history_table(matches),hide_index=True,use_container_width=True)


        with predict_tab:
            st.markdown('### Trend- and matchup-adjusted milestone estimates')
            st.warning('**Experimental / not validated:** these estimates include age (when available), sustained form trends and past games versus this opponent, but they are NOT calibrated probabilities. Injury status, projected lineups and opponent-wide defensive strength are not included.')
            pred_category=st.selectbox('Predict milestone category',list(STATS),key='predict_stat')
            age=player_age(int(p.PLAYER_ID))
            prediction, description=model_predictions(full,str(p.Opponent),pred_category,age)
            if prediction.empty:
                st.info(description)
            else:
                st.dataframe(prediction,hide_index=True,use_container_width=True)
                st.caption(description)
                st.markdown('### 🎯 Lower-risk and upside milestone finder')
                st.caption('Relative rankings within this player and selected statistic — not guarantees, betting advice, or validated probabilities. No bookmaker odds or expected value are used.')
                lower, upside = milestone_shortlist(prediction, full, pred_category)
                low_tab, high_tab = st.tabs(['🛡️ More attainable milestones', '🚀 Higher-upside milestones'])
                with low_tab:
                    st.caption('Highest available thresholds with an experimental model estimate of at least 70%.')
                    if lower.empty:
                        st.info('No milestone in this category meets the 70% model threshold.')
                    else:
                        st.dataframe(lower, hide_index=True, use_container_width=True)
                with high_tab:
                    st.caption('Ranks unusually high milestones (at least 35% above the player’s recent average) with model estimates between 8% and 45%. The first row is the most likely of these difficult milestones, not necessarily a good wager.')
                    if upside.empty:
                        st.info('No upside milestone meets these criteria in this category. Try another statistic.')
                    else:
                        st.dataframe(upside, hide_index=True, use_container_width=True)
                st.caption('For example, 4+ made threes for a player averaging 2.0 is an upside milestone. The model checks recent scoring trends, minutes and history versus the selected opponent before ranking it.')
                with st.expander('How the model works and its limitations'):
                    st.write('This experimental model weights up to 40 recent games, detects sustained changes in per-36-minute performance by comparing recent games against older non-overlapping games, and caps trend adjustments at 12%. Age modestly changes how much we trust an observed positive trend, if NBA.com birthdate is available. Up to five games against the selected opponent influence the estimate, with shrinkage for small samples. Recent minutes adjust opportunity. Normal-tail approximations are used for count milestones; smoothed frequencies are used for double/triple-doubles. This has NOT been backtested or calibrated. Team defensive strength, injuries, projected lineups, and uncertainty about future minutes are not yet incorporated.')



st.divider()

st.caption('Data: ESPN public NBA schedule and NBA.com stats via nba_api. Historical game logs are regular season only. Player availability and opponent team-wide defensive adjustments are not yet included. Experimental predictions are uncalibrated. Data may be delayed or rate-limited.')
