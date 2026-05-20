

import streamlit as st
import mysql.connector
import pandas as pd
import plotly.express as px

# DATABASE CONNECTION
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='stickwithfooty',
        password='DB_PASSWORD',
        database='swf'
    )

def evaluate_form(points):
    if points >= 13:
        return 'elite_form'
    elif points >= 10:
        return 'top_form'
    elif points >= 7:
        return 'good_form'
    elif points >= 4:
        return 'poor_form'
    else:
        return 'bottom_form'

def get_competitions(conn):
    cursor = conn.cursor()
    query = """
        SELECT c.competition_id, c.name, c.season_phase, MAX(m.season) 
        FROM competitions c
        JOIN matches m ON c.competition_id = m.competition_id
        GROUP BY c.competition_id, c.name, c.season_phase
        ORDER BY c.name
        """ # adding season_phase here to differentiate comp ID's AND season to get recent seasonal stats
    cursor.execute(query)
    comps = cursor.fetchall()
    cursor.close()
    return comps

# RANKING FUNCTION
def rank_teams(conn, competition_id, stat_filter, current_season, sample_size='', location_filter='', mode=None): # added current_season variable here
    def calc_results_to_points(stat):
        return sum(convert_result_to_points(x) for x in stat)
    def convert_result_to_points(result):
        result = result.strip().lower()  # incase i ever type the data entry with a capital W or space, this allows for Win or win to be accepted by the script
        if result == 'win':
            return 3
        elif result == 'draw':
            return 1
        else:
            return 0
    def get_all_teams_in_competition(conn, competition_id):
        cursor = conn.cursor()
        query = """
        SELECT DISTINCT ms.team_id, t.name
        FROM match_stats ms
        JOIN matches m ON ms.match_id = m.match_id
        JOIN teams t ON ms.team_id = t.team_id
        WHERE m.competition_id = %s
        """
        cursor.execute(query, (competition_id,))
        result = cursor.fetchall()
        cursor.close()
        return result  # List of (team_id, name)

    def get_stats_last_n(conn, team_id, competition_id, stat_filter, n, location_filter, mode):
        cursor = conn.cursor()

        limit_clause = "LIMIT %s" if n else ""

        location_condition = ""
        if location_filter == "home":
            location_condition = "AND m.home_team_id = ms.team_id"
        elif location_filter == "away":
            location_condition = "AND m.away_team_id = ms.team_id"

        if mode == 'offense':
        # this is just regular or standard stats that will be called since all data entry for stats are offense based
        # adding m.season to both offense and defense for recent season pull
            query = f"""
            SELECT ms.{stat_filter}
            FROM match_stats ms
            JOIN matches m ON ms.match_id = m.match_id
            WHERE ms.team_id = %s AND m.competition_id = %s AND m.season = %s
            {location_condition}
            ORDER BY m.match_date DESC
            {limit_clause}
            """
        elif mode == 'defense':
        # these will be oppenents offense stats earned or allowed by selected team(s)
            query = f"""
            SELECT opp.{stat_filter}
            FROM match_stats ms
            JOIN match_stats opp ON ms.match_id = opp.match_id AND opp.team_id <> ms.team_id
            JOIN matches m ON ms.match_id = m.match_id
            WHERE ms.team_id = %s AND m.competition_id = %s AND m.season = %s 
            {location_condition}
            ORDER BY m.match_date DESC
            {limit_clause}
            """

    # this sets parameters for statistical sample size of overall, last 3 or last 5 or whatever
    # season specififer here as well
        if n:
            params = (team_id, competition_id, current_season, n)
        else:
            params = (team_id, competition_id, current_season)

        cursor.execute(query, params)

        rows = cursor.fetchall()
        cursor.close()
        return [row[0] for row in rows if row[0] is not None]

    # Step 1: Get all teams
    teams = get_all_teams_in_competition(conn, competition_id)

    # Step 2: Loop and gather stat totals
    rankings = []
    for team_id, name in teams:
        stat_list = get_stats_last_n(conn, team_id, competition_id, stat_filter, sample_size, location_filter,mode)
        if not stat_list:
            continue

        if stat_filter == 'result':
            #
            stat_total = calc_results_to_points(stat_list)
        else:
            stat_total = sum(stat_list)

        if mode == 'defense':
            stat_total = stat_total

        rankings.append((name, stat_total))

    # Step 3: Sort by stat total
    rankings.sort(key=lambda x: x[1], reverse=(mode == 'offense'))
    #for defense stats, lower is better so reverse = false
    return {
        'top':rankings[:5],
        'bottom':rankings[-5:][::-1]
    }

# DATA FOR AUDIT SNAPSHOT DASHBOARD
def get_audit_snapshot(conn,selected_date):
    # get data from snapshot table
    query="""
    SELECT
    CASE WHEN c.name = 'Major League Soccer' THEN 'MLS' ELSE c.name END AS League,
    h.name AS Home,
    a.name AS Away,
    snap.home_zscore AS hZ, snap.away_zscore AS aZ, snap.TotalZ, snap.ZDiff,
    snap.hconv AS hC, snap.aconv AS aC, snap.ConvDiff,
    snap.H_Mom, snap.A_Mom, snap.MomDiff,
    snap.H_Leak, snap.zH_Leak, snap.A_Leak, snap.zA_Leak,
    snap.H_Risk, snap.A_Risk,
    -- h_cat.name AS H_Catalyst, a_cat.name AS A_Catalyst -- was gonna use for pop up purposes but too technical for now, will use later though. i remeber in css there is a 'hover' function that can be used for this
    h_idx.win_pct AS h_win_pct,
    h_idx.samples AS h_samples,
    a_idx.win_pct AS a_win_pct,
    a_idx.samples AS a_samples
    FROM t_audit_snapshot snap
    JOIN teams h ON snap.home_id = h.team_id
    JOIN teams a ON snap.away_id = a.team_id
    JOIN competitions c ON snap.comp = c.competition_id
    JOIN v2_match_pressure_profile pp ON snap.match_id = pp.match_id
    LEFT JOIN team_Stress_index h_idx ON h.team_id = h_idx.team_id AND pp.home_stresslevel = h_idx.stress_zone
    LEFT JOIN team_Stress_index a_idx ON a.team_id = a_idx.team_id AND pp.away_stresslevel = a_idx.stress_zone
    -- LEFT JOIN teams h_cat ON snap.H_prevopp = h_cat.team_id
    -- LEFT JOIN teams a_cat ON snap.a_prevopp = a_cat.team_id
    WHERE snap.match_date = %s
    """
    return pd.read_sql(query,conn,params=[selected_date])

# ODDS DATA
def get_alpha_report(conn, selected_date):
    date_str = str(selected_date) # converting date to string value to prevent sql driver hiccups

    # first query is to get H2H odds (outright moneyline)
    h2h_query = """
    SELECT
    po.match_id, 
    'H2H' as market_type, 
    idx.stress_zone AS `Matchup Profile`,
    po.selection AS `Selection`, 
    po.price AS `Price`, 
    po.house_edge AS `House Tax`,
    ROUND(((idx.win_pct / 100) - po.fair_prob), 4) AS `SWF Score`,
    idx.win_pct AS `Win rate %`,
    idx.loss_pct AS `Loss rate %`,
    idx.draw_pct AS `Draw rate %`,
    CAST(idx.samples AS SIGNED) AS `Samples`,
    po.fair_prob AS `Market Probability %`,
    CASE WHEN a.A_Risk > 0 OR a.H_Risk > 0 THEN 'Yes' ELSE 'None' END AS `Risk`
    FROM processed_odds po
    JOIN t_audit_snapshot a ON po.match_id = a.match_id
    JOIN v2_match_pressure_profile pp ON po.match_id = pp.match_id 
    JOIN team_name_mapper m ON po.selection = m.api_name
    LEFT JOIN team_stress_index idx ON m.db_team_id = idx.team_id AND (CASE WHEN m.db_team_id = pp.home_team_id THEN pp.Home_StressLevel ELSE pp.Away_StressLevel END) = idx.stress_zone
    WHERE po.market = 'h2h' AND a.match_date = %s AND po.selection != 'Draw' AND ((idx.win_pct / 100) - po.fair_prob) > 0 AND idx.samples >= 6
    """

    # second query for totals odd (over under)
    totals_query= """
    SELECT
    po.match_id,
    'Totals' AS market_type,
    CONCAT(t_h.name, ' v ', t_a.name) AS `Match`,
    CAST(po.point AS DECIMAL(3,1)) AS `Point`, -- format the prices to show just 1 decimal (2.5)
    po.selection AS `Selection`,
    po.price AS `Price`,
    po.house_edge AS `House Tax`,

    -- POISSON CALCULATION SUB-ENGINE

    ROUND(
        CASE 
        WHEN po.selection = 'Under' THEN CASE
            -- 1.5 line means either exactly 0 or 1
            WHEN po.point = 1.5 THEN
                EXP(-(lb.AVG_Goals * (1 + (a.TotalZ /10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) *
                (1 + (lb.AVG_Goals * (1 + (a.TotalZ /10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) - po.fair_prob
            -- 2.5 line means either exactly 0, 1 or 2
            WHEN po.point = 2.5 THEN
                EXP(-(lb.AVG_Goals * (1 + (a.TotalZ /10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) *
                (1 + (lb.AVG_Goals * (1 + (a.TotalZ /10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0))) +
                (POWER((lb.AVG_Goals * (1 + (a.TotalZ /10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0))), 2) / 2)) - po.fair_prob
            ELSE 0.00
        END
        WHEN po.selection = 'Over' THEN CASE
            -- over is 1 minus the probabality of 0 or 1 goals
            WHEN po.point = 1.5 THEN
                1 - (EXP(-(lb.AVG_Goals * (1 + (a.TotalZ / 10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) * 
                (1 + (lb.AVG_Goals * (1 + (a.TotalZ / 10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) ) - po.fair_prob
            -- over is 1 minus the probability of 0, 1 or 2 goals
            WHEN po.point = 2.5 THEN
                1 - (EXP(-(lb.AVG_Goals * (1 + (a.TotalZ / 10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0)))) * 
                (1 + (lb.AVG_Goals * (1 + (a.TotalZ / 10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0))) + 
                (POWER((lb.AVG_Goals * (1 + (a.TotalZ / 10)) * (((a.hconv + a.aconv) / 2) / NULLIF(lb.ConvBaseline, 0))), 2) / 2)) ) - po.fair_prob
            ELSE 0.00 END
        ELSE 0.00 END, 4
    ) AS `SWF Score`,

    lb.AVG_Goals AS `League AVG`,
    lb.chaos_index AS `League Chaos Index`,
    ROUND((a.H_Mom + a.A_Mom), 2) AS `Total Momentum`,
    ROUND((a.H_Leak + a.A_Leak), 2) AS `Total Leak`,
    CASE WHEN a.A_Risk > 0 OR a.H_Risk > 0 THEN 'Yes' ELSE 'None' END AS `Risk`
    FROM processed_odds po
    JOIN t_audit_snapshot a ON po.match_id = a.match_id
    JOIN matches m ON a.match_id = m.match_id
    JOIN teams t_h ON m.home_team_id = t_h.team_id
    JOIN teams t_a ON m.away_team_id = t_a.team_id
    JOIN v_league_baselines lb ON a.comp = lb.Comp AND m.season = lb.season
    WHERE po.market = 'totals' AND po.point IN (2.5, 1.5) AND a.match_date = %s HAVING `SWF Score` > 0
    """
    df_h2h = pd.read_sql(h2h_query,conn,params=[date_str])
    df_totals = pd.read_sql(totals_query,conn,params=[date_str])

    combined_df = pd.concat([df_h2h,df_totals], ignore_index=True)
    if not combined_df.empty:
        return combined_df.sort_values('SWF Score', ascending=False)
    return pd.DataFrame() # returns empty df if no alphas found

# color styling -- this shit took forever and might constantly be updated
def style_audit_report(df):
    def apply_mismatch_logic(row): # this will set a foundation for columns that i want to apply any mismatching or color coding logic to--if metrics compliment each other; for example, high momentum v high leak
        styles = pd.Series('', index=row.index)

        # ------- ZONE SPECIALIST HIGHLIGHT (70% WIN RATE minimum 8 games)

        specialist_style = 'background-color: #28a745; color: white; font-weight: bold;'
        if row['h_win_pct'] >= 70.0 and row['h_samples'] >= 8:
            styles['Home'] = specialist_style
        if row['a_win_pct'] >= 70.0 and row['a_samples'] >= 8:
            styles['Away'] = specialist_style

        # ---- CLINICAL EFFICIENCY(conversion) MISMATCH -----

        # highlight matches where ConvDiff larger than .30 and atleast one team is below 0.90
        convdiff_threshold = 0.30
        teamconv_threshold = 0.90

        # for home team (HConv)
        if row['ConvDiff'] >= convdiff_threshold and row['aC'] < teamconv_threshold:
            styles['hC'] = 'background-color: #1a472a; color: #00ff00; font-weight: bold;'
            styles['ConvDiff'] = 'colorL #00ff00; font-weight: bold;'
        # for away team (AConv)
        elif row['ConvDiff'] <= -convdiff_threshold and row['hC'] < teamconv_threshold:
            styles['aC'] = 'background-color: #1a472a; color: #00ff00; font-weight: bold;'
            styles['ConvDiff'] = 'colorL #ff4b4b; font-weight: bold;' # red
        else:
        # regular individual conv highlight, green for high, red for bad duh
            if row['hC'] > 1.59: styles['hC'] = 'color: #28a745; font-weight: bold;'
            elif row ['hC'] < 0.79: styles['hC'] = 'color: #dc3545; font-weight: bold;'

            if row['aC'] > 1.59: styles['aC'] = 'color: #28a745; font-weight: bold;'
            elif row['aC'] < 0.79: styles['aC'] = 'color: #dc3545; font-weight: bold;'

        # ------- RISK COLUMN HIGHLIGHT ------- 

        if row['H_Risk'] == 2: styles['H_Risk'] = 'background-color: #721c24; color: white;' # dark red
        elif row['H_Risk'] == 1: styles['H_Risk'] = 'background-color: #856404; color: white;' # yellowish warning
        elif row['H_Risk'] == 0: styles['H_Risk'] = 'color: #666666;' # greyed out


        if row['A_Risk'] == 2: styles['A_Risk'] = 'background-color: #721c24; color: white;' 
        elif row['A_Risk'] == 1: styles['A_Risk'] = 'background-color: #856404; color: white;' 
        elif row['A_Risk'] == 0: styles['A_Risk'] = 'color: #666666;' 

        # ------- MOMENTUM COLUMN HIGHLIGHT ---------

        if row['H_Mom'] > 1.5: styles['H_Mom'] = 'color: #28a745; font-weight: bold;'
        elif row ['H_Mom'] < 0.75: styles['H_Mom'] = 'color: #dc3545; font-weight: bold;'

        if row['A_Mom'] > 1.5: styles['A_Mom'] = 'color: #28a745; font-weight: bold;'
        elif row['A_Mom'] < 0.75: styles['A_Mom'] = 'color: #dc3545; font-weight: bold;'

        # ------- LEAK COLUMN HIGHLIGHT ------------
        if row['H_Leak'] > 1.40: styles['H_Leak'] = 'color: #dc3545; font-weight: bold;'
        elif row['H_Leak'] < 0.80: styles['H_Leak'] = 'color: #28a745; font-weight: bold;'

        if row['A_Leak'] > 1.40: styles['A_Leak'] = 'color: #dc3545; font-weight: bold;'
        elif row['A_Leak'] < 0.80: styles['A_Leak'] = 'color: #28a745; font-weight: bold;'

        # -------- TOTAL Z COLUMN HIGHLIGHT -------

        if row['hZ'] < -0.99: styles['hZ'] = 'color: #007498; font-weight: bold;'
        if row['aZ'] < -0.99: styles['aZ'] = 'color: #007498; font-weight: bold;'

        return styles

    return df.style.apply(apply_mismatch_logic, axis=1).format(precision=2)

def style_alpha_report(df):
    if df.empty: return df 
    # color gradient (Max to Min) from https://colordesigner.io/gradient-generator for future use
    # using these colors for thresholds
    green_color = '#00b224'  # top candidates
    orange_color = '#b46f00' # mid candidates
    red_color = '#d53411'    # low margin candidates

    def apply_color(row):
        styles = pd.Series('', index=row.index)
        val = row['SWF Score']
        
        if val >= 0.12:
            color = green_color
        elif 0.06 <= val < 0.12:
            color = orange_color
        else:
            color = red_color
            
        styles['SWF Score'] = f'color: {color}; font-weight: bold;'
        return styles

    return df.style.apply(apply_color, axis=1)

def get_ticker_metrics(conn):
    cursor = conn.cursor(dictionary=True)
    # Using COALESCE to force 0.00 instead of None if portfolio table is empty
    cursor.execute("""
        SELECT 
            COALESCE(CAST(SUM(stake_amount) AS DOUBLE), 0.00) as total_risked,
            COALESCE(CAST(SUM(net_profit) AS DOUBLE), 0.00) as net_profit,
            COUNT(CASE WHEN settled_status = 'won' THEN 1 END) as wins,
            COUNT(CASE WHEN settled_status = 'lost' THEN 1 END) as losses
        FROM portfolio_tickets;
    """)
    metrics = cursor.fetchone()
    cursor.close()
    return metrics



# STREAMLIT APP LAYOUT
def main():
    st.set_page_config(page_title='SWF Lab', layout='wide')
    st.title('STICK WITH FOOTY - ranking (prototype)')

    # copied over stat_map from scratch file -- this is what was being used in user_input
    stat_map = {
        'offense': {
            'Goals scored': 'totalgoals',
            'Corners': 'totalcorners',
            'Shots committed': 'totalshots',
            'Shots On Target': 'totalSOT',
            '1H Goals scored': 'firsthalf_goals',
            '2H Goals scored': 'secondhalf_goals',
            '1H Corners': 'firsthalf_corners',
            '2H Corners': 'secondhalf_corners',
            '1H Shots committed': 'firsthalf_shots',
            '2H Shots committed': 'secondhalf_shots',
            '1H Shots On Target': 'firsthalf_SOT',
            '2H Shots On Target': 'secondhalf_SOT',
            'result': 'result'
        },
        'defense':{
            'Goals conceded': 'totalgoals',
            'Corners conceded': 'totalcorners',
            'Shots conceded': 'totalshots',
            'Shots On Target conceded': 'totalSOT',
            '1H Goals conceded': 'firsthalf_goals',
            '2H Goals conceded': 'secondhalf_goals',
            '1H Corners conceded': 'firsthalf_corners',
            '2H Corners conceded': 'secondhalf_corners',
            '1H Shots conceded': 'firsthalf_shots',
            '2H Shots conceded': 'secondhalf_shots',
            '1H Shots On Target conceded': 'firsthalf_SOT',
            '2H Shots On Target conceded': 'secondhalf_SOT',
            'result': 'result'
        }
        }


    # connect to database
    conn = get_db_connection()

    #competition selection
    competitions = get_competitions(conn)

                ###### FINANCIAL METRIC TRACKER #######
    with st.sidebar:
        st.markdown("### Portfolio Ticker")
        #       -- acounting anchor
        lifetime_deposits = 50.00 # my out-of-pocket deposits
        initial_dk_capital = 0.48   # initial starting balance in draftkings
        #   -- pull the data from database table
        portfolio = get_ticker_metrics(conn)
        
        current_trade_profits = portfolio['net_profit']
        total_risked = portfolio['total_risked']

        current_bankroll = initial_dk_capital + lifetime_deposits + current_trade_profits

        lifetime_net_growth = current_bankroll - lifetime_deposits
        lifetime_roi_pct = (lifetime_net_growth / lifetime_deposits * 100) if lifetime_deposits > 0 else 0.00
        active_yield_pct = (current_trade_profits / total_risked * 100) if total_risked > 0 else 0.00

        ticker_color = "#00b224" if lifetime_net_growth >= 0 else "#d53411"
        ticker_arrow = "▲" if lifetime_net_growth >= 0 else "▼"

        st.html(
            f"""
            <div style="background-color: #111111; padding: 12px; border-radius: 6px; border-left: 5px solid {ticker_color}; margin-bottom: 15px;">
                <p style="margin: 0; font-size: 0.8rem; color: #888888; text-transform: uppercase; font-weight: bold; letter-spacing: 0.05em;">Net Bankroll Value</p>
                <h2 style="margin: 5px 0; color: #ffffff; font-family: monospace; font-size: 1.8rem;">${current_bankroll:.2f}</h2>
                <p style="margin: 0; font-size: 0.9rem; color: {ticker_color}; font-weight: bold; font-family: monospace;">
                    Lifetime: {ticker_arrow} ${lifetime_net_growth:+.2f} ({lifetime_roi_pct:+.2f}%)
                </p>
            </div>
            """, 
        )
        
        # --- RISK MANAGEMENT METRIC MATRIX ---
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.caption("🛡️ Funded Capital")
            st.markdown(f"**${lifetime_deposits:.2f}**")
            
            st.caption("🚀 Active Yield")
            yield_color = "#28a745" if current_trade_profits >= 0 else "#dc3545"
            st.html(f"<span style='color:{yield_color}; font-weight:bold;'>{active_yield_pct:+.2f}%</span>")
            
        with col_t2:
            st.caption("🏁 Record Grid")
            st.markdown(f"**{portfolio['wins']}W** - **{portfolio['losses']}L**")
            
            st.caption("🎲 Risked Volume")
            st.markdown(f"**${total_risked:.2f}**")
            
        st.divider()

    
    comp_dict = {} # create unique label like 'comp (season_phase)' -- how i had it before, i was overwriting the prior ID everytime the new comp ID (with same name) executed
    season_map = {} #similar dict for seasons... this will store MAX season for each comp
    for cid, name, season_phase, max_season in competitions:
        label = f"{name} ({season_phase.capitalize()})" if season_phase else name # this standardizes labels to allow detection (ex: liga mx (clausura))
        comp_dict[label] = cid 
        season_map[cid] = max_season # links ID to latest season

    # UI SELECTION
    # everything from UI gate to 'safety check' is just for the aethetic purpose of a radio button selection for seasonal phases lol

    # now select box has unique keys for every comp ID 
    unique_competition = sorted(list(set([label.split(" (")[0] for label in comp_dict.keys()]))) # strips the phase for primary selector; so i dont have two 'Primera A' entries in dropdown like i do in DB--just one
    competition_name = st.selectbox('Pick a competition', unique_competition)

    # UI 'gate' that checks if the league has multiple phases
    available_phases = [l for l in comp_dict.keys() if l.startswith(competition_name)]
    # if list contains a ( , it means there are distinct apertura and clausura id's for that comp
    if any (" (" in p for l in available_phases for p in [l]):
        phase_choice = st.radio(
            'Select seasonal phase', ['Apertura', 'Clausura'],
            horizontal=True
            )
        # rebuild the full 'label' to get the correct CID (ex: 'Primera A (Apertura)')
        final_label = f"{competition_name} ({phase_choice})"
        competition_id = comp_dict[final_label]
    else:
        # leagues with no phases
        competition_id = comp_dict.get(competition_name)

    # safety check and execution
    if competition_id:
        current_season = season_map[competition_id]
        st.caption(f"Status: Auditing **{competition_name}** | Season: **{current_season}**")

    # this here gets max (recent) season for selected comp
    current_season = season_map[competition_id]
    
    # optional flexibility -- only to alow user to override current season for another but for now it defaults to current season found in database
    # selected_season = st.sidebar.number_input('Season', value=int(current_Season))

    # to determine if 'phase' radio option should show only if seasonal phases exists for league
    has_phases = "(" in competition_name

    #sample selection
    sample_option = st.radio('Sample size', ['Overall', 'Last 3', 'Last 5'], index=0, horizontal=True)

    sample_map = {'Overall': None,'Last 3':3, 'Last 5':5}
    sample_size = sample_map[sample_option]
    st.caption(f"Displaying statistics for the {current_season} season")

    #STATIC OFFENSE/DEFENSE -- default will be overall for location and totalgoals in sql db

    best_attack = rank_teams(conn, competition_id, stat_filter='totalgoals', current_season=current_season, sample_size=sample_size,location_filter='overall',mode='offense')
    best_defense = rank_teams(conn, competition_id, stat_filter='totalgoals', current_season=current_season, sample_size=sample_size, location_filter='overall',mode='defense')

    #convert to DataFrame for displaying static data

    df_best_attack = pd.DataFrame(best_attack['top'], columns=['Team', 'Goals Scored'])
    df_worst_attack = pd.DataFrame(best_attack['bottom'], columns=['Team', 'Goals Scored'])
    df_best_defense = pd.DataFrame(best_defense['top'], columns=['Team', 'Goals Conceded'])
    df_worst_defense = pd.DataFrame(best_defense['bottom'], columns=['Team', 'Goals Conceded'])

    col1, col2 = st.columns(2)

    col3, col4 = st.columns(2)

    # visuals

    with col1:
        st.subheader(f'BEST ATTACK')
        st.table(df_best_attack.set_index('Team'))
    with col2:
        st.subheader(f'WORST ATTACK')
        st.table(df_worst_attack.set_index('Team'))

    with col3:
        st.subheader(f'BEST DEFENSE')
        st.table(df_best_defense.set_index('Team'))
    with col4:
        st.subheader(f'WORST DEFENSE')
        st.table(df_worst_defense.set_index('Team'))

    # this below will allow users to view 'advanced' set of stats such as first half goals, SOT, etc
    with st.expander('See more statistics'):
        stat_mode = st.radio('Stat mode', ['offense', 'defense'], index=0)
        location_filter = st.radio("Location", ["overall", "home", "away"], index=0)
        stat_label = st.selectbox('pick a stat:', list(stat_map[stat_mode].keys()))
        stat_filter = stat_map[stat_mode][stat_label]

        ranking = rank_teams(conn, competition_id, stat_filter,current_season=current_season, sample_size=sample_size, location_filter=location_filter,mode=stat_mode)

        df_top = pd.DataFrame(ranking['top'], columns=['Team', stat_label])
        df_bottom = pd.DataFrame(ranking['bottom'], columns=['Team', stat_label])

         # --- NEW TOGGLE & VISUALIZATION ---
        view_format = st.radio("View Format", ["📊 Visual", "🔢 Table"], index=0, horizontal=True)

        if view_format == "🔢 Table":
            st.write('Top 5')
            st.table(df_top)
            st.write('Bottom 5')
            st.table(df_bottom)

        else:
            # Combine data for a unified "League Landscape" chart
            # We reverse df_bottom to ensure the absolute worst is at one end
            df_viz = pd.concat([
                df_top.assign(Category='Top 5'), 
                df_bottom.assign(Category='Bottom 5')
            ])

            # Decide color based on mode (Green for good offense, Red for bad defense)
            # Logic: If offense, Top 5 = Green. If defense, Top 5 (highest conceded) = Red.
            color_theme = ['#28a745', '#dc3545'] if stat_mode == 'offense' else ['#dc3545', '#28a745']

            fig = px.bar(
                df_viz, 
                x=stat_label, 
                y='Team', 
                color='Category',
                text=stat_label,  # <--- NEW: Tells Plotly which column to use for labels
                orientation='h',
                title=f"{competition_name} - {stat_label} Landscape ({sample_option})",
                color_discrete_sequence=color_theme,
                template="plotly_dark"
            )

            # --- Text Positioning and Formatting ---
            fig.update_traces(
                textposition='outside', # Places numbers at the end of the bars
                texttemplate='%{text}', # Formats the text (e.g., adds decimals if needed)
                cliponaxis=False         # Ensures numbers aren't cut off at the edge
            )

            # Sort the Y-axis so the highest value is at the top
            fig.update_layout(
                yaxis={'categoryorder':'total ascending'},
                xaxis={'showticklabels': False}, # Optional: Hides X-axis numbers for a cleaner look since they are now on the bars
                showlegend=True,
                margin=dict(l=20, r=20, t=40, b=20),
                height=450
            )

            st.plotly_chart(fig, use_container_width=True)


                                                        # ------ DASHBOARD CODE BELOW ---------

    head_col1, head_col2 = st.columns([4,1])
    with head_col1:
        st.title("Matchday Audit Dashboard 📊")


    #Grab specific match dates in the snapshot
    cursor=conn.cursor()
    cursor.execute("""
        SELECT DISTINCT match_date
        FROM t_audit_snapshot
        ORDER BY match_date""")
    available_dates = [row[0] for row in cursor.fetchall()]

    if not available_dates:
        st.warning("Snapshot table is empty. Stats Pipeline is not refreshed.")
        return

    with head_col2:
        st.write("##")
        selected_date = st.selectbox("",available_dates, label_visibility='collapsed')


    # a toggle option for simplified viewing
    show_advanced = st.checkbox('Show advanced match physics', value=False) # false value leaves box unchecked by default

    # DATA EXECUTION PART
    df = get_audit_snapshot(conn,selected_date)

    if not df.empty: # tip: style everything first. the entire dataframe (df) and then edit what to show and not
        styled_df = style_audit_report(df)

        # now refine/adjust visibility of what i want the user to see on the webapp
        cols_to_show = ['League','Home','Away','hC','aC',
        'H_Mom','A_Mom','H_Leak','A_Leak','H_Risk','A_Risk']
        if show_advanced:
            cols_to_show = ['League','Home','Away','hZ','aZ','TotalZ','ZDiff','hC','aC','ConvDiff',
        'H_Mom','A_Mom','MomDiff','H_Leak','zH_Leak','A_Leak','zA_Leak','H_Risk','A_Risk']


        # now interactive rendering for dataframe begins below
        st.caption(f"Showing {len(df)} matches for {selected_date}")

        # headers are clickable to sort any column :) -- fuck typing sql queries out 
        top_dashboard_container = st.empty()
        event = st.dataframe(
            styled_df,
            use_container_width = True,
            height = 900,
            hide_index=True, # removes numbered columns
            column_order=cols_to_show,
            on_select='rerun', # tells streamlit to refresh when a row is clicked
            selection_mode='single-row', # limits selection to one match at a time
            column_config={
            "H_Risk": st.column_config.NumberColumn(
                "Home Risk", 
                help="🔎 Risk flags trigger when a team is either: in danger of conceding +1.7 goals, \n has over a 55% chance of losing the match -- OR BOTH 🔴 -- due to the impact left by their previous opponent."
            ),
            "A_Risk": st.column_config.NumberColumn(
                "Away Risk", 
                help="🔎 Risk flags trigger when a team is either: in danger of conceding +1.7 goals, \n has over a 55% chance of losing the match -- OR BOTH 🔴 -- due to the impact left by their previous opponent."
            ),
            "hC": "Home Conversion",
            "aC": "Away Conversion",
            "hZ": "Home Z",
            "aZ": "Away Z",
            # Hide these columns from the table view explicitly just in case, we only need them for the logic
            "h_win_pct": None,
            "h_samples": None,
            "a_samples": None,
            "a_win_pct": None})

                             # --- DYNAMIC MATCH PROFILE SNAPSHOT --- 
        if event.selection.rows:
            selected_index = event.selection.rows[0]
            selected_match = df.iloc[selected_index]
            with top_dashboard_container:
                with st.popover(f"Deep Dive: {selected_match['Home']} vs {selected_match['Away']}", use_container_width=True):

                    st.markdown(f"### Forensic Profile: {selected_match['League']}")

                    # row 1 -- the match physics

                    m_col1,m_col2,m_col3,m_col4 = st.columns(4)
                    with m_col1:
                        st.metric('Efficiency Edge', f"{selected_match['ConvDiff']:.2f}")
                    with m_col2:
                        st.metric('Total Match Volume', f"{selected_match['TotalZ']:.2f}")
                    with m_col3:
                        hrisk_status = f'{selected_match['Home']}: CLEAN' if selected_match['H_Risk'] == 0 else f'{selected_match['Home']}: CAUTION'
                        st.metric('Risk status', hrisk_status)
                    with m_col4:
                        arisk_status = f'{selected_match['Away']}: CLEAN' if selected_match['A_Risk'] == 0 else f'{selected_match['Away']}: CAUTION'
                        st.metric('Risk status', arisk_status)

                    st.divider()

                    # row 2 -- team physics

                    t_col1,t_col2 = st.columns(2)
                    t_col1.metric('Home Momentum', f"{selected_match['H_Mom']:.2f}")
                    t_col2.metric('Away Momentum', f"{selected_match['A_Mom']:.2f}")

    else:
        st.info(f"No scheduled matches found for {selected_date}")

    st.divider()

                                                 # ----- ODDS MARKET DASHBOARD CODE BELOW -------

    st.title('Market Price Evaluator ⚖️')

    market_filter = st.radio("Selection Focus", ['H2H','Totals'], horizontal=True)
    alpha_df = get_alpha_report(conn,selected_date)

    if not alpha_df.empty:
        # route the dataset based on focus selection
        filtered_df = alpha_df[alpha_df['market_type'] == market_filter].copy()

        if not filtered_df.empty:
            # executes the color style 
            styled_alpha = style_alpha_report(filtered_df)

            if market_filter == 'H2H':
                visible_columns = [
                    "Matchup Profile", "Selection", "Price", "House Tax", 
                    "SWF Score", "Win rate %", "Loss rate %", "Draw rate %", "Samples", 
                    "Market Probability", "Risk"
                ]
                column_formats = {
                    "House Tax": st.column_config.NumberColumn("House Tax", format="%.2f%%"),
                    "SWF Score": st.column_config.NumberColumn("SWF Score", format="%.2f%%"),
                    "Win rate %": st.column_config.NumberColumn("Win rate %", format="%.1f%%"),
                    "Loss rate %": st.column_config.NumberColumn("Loss rate %", format="%.1f%%"),
                    "Draw rate %": st.column_config.NumberColumn("Draw rate %", format="%.1f%%"),
                    "Market Probability": st.column_config.NumberColumn("Market Probability", format="%.2f%%"),
                    "Samples": st.column_config.NumberColumn("Samples", format="%d") # enforces strict whole number 
                }
            else:
                visible_columns = [
                    "Match", "Point", "Selection", "Price", "House Tax", 
                    "SWF Score", "League AVG", "League Chaos index", 
                    "Total Momentum", "Total Leak", "Risk"
                ]
                column_formats = {
                    "Point": st.column_config.NumberColumn("Point", format="%.1f"), # Locks display line to single decimal
                    "House Tax": st.column_config.NumberColumn("House Tax", format="%.2f%%"),
                    "SWF Score": st.column_config.NumberColumn("SWF Score", format="%.2f%%"),
                    "League AVG": st.column_config.NumberColumn("League AVG", format="%.2f"),
                    "League Chaos index": st.column_config.NumberColumn("League Chaos index", format="%.2f"),
                    "Total Momentum": st.column_config.NumberColumn("Total Momentum", format="%.2f"),
                    "Total Leak": st.column_config.NumberColumn("Total Leak", format="%.2f")
                }
            st.dataframe(
                styled_alpha,
                use_container_width=True,
                hide_index=True,
                column_order=visible_columns,
                column_config=column_formats
                )
        else:
            # Triggers if there are overall alphas for the day, but none match this specific radio selection
            st.info(f"No high value trade detected for the {market_filter} market on this date.")
    else:
        # Triggers if the master database query yields 0 rows for the entire date
        st.info("No valuable trades detected for this slate.")


    conn.close() 

if __name__ == '__main__':
    main()



