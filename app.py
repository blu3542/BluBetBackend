from flask import Flask, jsonify, request
import requests
import pandas as pd
from flask_cors import CORS 
import numpy as np





app = Flask(__name__)

CORS(app)



api_key = "d9157f32a30da6c5e3954811876be039"
markets = "h2h"
regions = "us,us2,eu"
oddsFormat = "american"

# API call to get odds from other games
get_pinnacle_odds = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={api_key}&regions={regions}&markets={markets}&oddsFormat={oddsFormat}&bookmakers=pinnacle"
get_overvalued_odds = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={api_key}&regions={regions}&markets={markets}&oddsFormat={oddsFormat}"

# Function to get pinnacle odds
def obtain_pinnacle_odds(API_Endpoint):
    response = requests.get(API_Endpoint)
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return pd.DataFrame()

    games_with_pinnacle_odds = []
    for game in data:
        for bookmaker in game['bookmakers']:
            if bookmaker['key'] == 'pinnacle':
                for market in bookmaker['markets']:
                    if market['key'] == 'h2h':  # head-to-head market
                        outcomes = market['outcomes']
                        games_with_pinnacle_odds.append({
                            'Game ID': game['id'],
                            'Sport': game['sport_title'],
                            'Commence Time': game['commence_time'],
                            'Home Team': game['home_team'],
                            'Away Team': game['away_team'],
                            'Home Odds': next((outcome['price'] for outcome in outcomes if outcome['name'] == game['home_team']), None),
                            'Away Odds': next((outcome['price'] for outcome in outcomes if outcome['name'] == game['away_team']), None)
                        })

    pinnacle_df = pd.DataFrame(games_with_pinnacle_odds)
    return pinnacle_df

# Function to calculate implied probability from American odds
def implied_prob_from_american(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return (-odds) / (-odds + 100)

# Function to remove vig and calculate true probabilities
def remove_vig(home_odds, away_odds):
    home_prob = implied_prob_from_american(home_odds)
    away_prob = implied_prob_from_american(away_odds)
    total_prob = home_prob + away_prob
    true_home_prob = home_prob / total_prob
    true_away_prob = away_prob / total_prob
    return true_home_prob, true_away_prob

# Convert true probabilities back to American odds
def prob_to_american_odds(prob):
    if prob > 0.5:  # For favorites (negative odds)
        return round(-100 / ((1 / prob) - 1))
    else:  # For underdogs (positive odds)
        return round((100 / prob) - 100)

# Function to fetch and compare odds, removing vig, and finding the best value
def fetch_and_compare_odds():
    response = requests.get(get_overvalued_odds)
    if response.status_code == 200:
        data = response.json()
    else:
        print(f"Error: Unable to fetch data (Status code: {response.status_code})")
        return pd.DataFrame()

    # Fetch pinnacle odds
    pinnacle_df = obtain_pinnacle_odds(get_pinnacle_odds)
    best_pick_data = []
    
    # Loop over games to compare odds and find the best picks
    for game in data:
        game_id = game['id']
        pinnacle_row = pinnacle_df[pinnacle_df['Game ID'] == game_id]
        if pinnacle_row.empty:
            continue
        
        home_odds_pinnacle = pinnacle_row['Home Odds'].values[0]
        away_odds_pinnacle = pinnacle_row['Away Odds'].values[0]
        
        # Remove vig
        true_home_prob, true_away_prob = remove_vig(home_odds_pinnacle, away_odds_pinnacle)
        
        # Convert back to American odds
        line_to_beat_home = prob_to_american_odds(true_home_prob)
        line_to_beat_away = prob_to_american_odds(true_away_prob)

        best_home_value = None
        best_away_value = None
        best_home_bookmaker = None
        best_away_bookmaker = None
        
        for bookmaker in game['bookmakers']:
            if bookmaker['key'] != 'pinnacle':
                for market in bookmaker['markets']:
                    if market['key'] == 'h2h':
                        outcomes = market['outcomes']
                        home_odds_other = next((outcome['price'] for outcome in outcomes if outcome['name'] == game['home_team']), None)
                        away_odds_other = next((outcome['price'] for outcome in outcomes if outcome['name'] == game['away_team']), None)
                        
                        # Home team comparison
                        if home_odds_other is not None:
                            if line_to_beat_home > 0 and home_odds_other > line_to_beat_home:
                                if best_home_value is None or home_odds_other > best_home_value:
                                    best_home_value = home_odds_other
                                    best_home_bookmaker = bookmaker['title']
                            elif line_to_beat_home < 0 and home_odds_other < line_to_beat_home:
                                if best_home_value is None or home_odds_other < best_home_value:
                                    best_home_value = home_odds_other
                                    best_home_bookmaker = bookmaker['title']

                        # Away team comparison
                        if away_odds_other is not None:
                            if line_to_beat_away > 0 and away_odds_other > line_to_beat_away:
                                if best_away_value is None or away_odds_other > best_away_value:
                                    best_away_value = away_odds_other
                                    best_away_bookmaker = bookmaker['title']
                            elif line_to_beat_away < 0 and away_odds_other < line_to_beat_away:
                                if best_away_value is None or away_odds_other < best_away_value:
                                    best_away_value = away_odds_other
                                    best_away_bookmaker = bookmaker['title']

        best_pick_data.append({
            'Game ID': game_id,
            'Sport': game['sport_title'],
            'Home Team': game['home_team'],
            'Away Team': game['away_team'],
            'Pinnacle Home Odds': home_odds_pinnacle,
            'Pinnacle Away Odds': away_odds_pinnacle,
            'Line to Beat Home Odds': line_to_beat_home,
            'Line to Beat Away Odds': line_to_beat_away,
            'Best Home Bookmaker': best_home_bookmaker,
            'Best Home Odds': best_home_value,
            'Best Away Bookmaker': best_away_bookmaker,
            'Best Away Odds': best_away_value
        })

    best_pick_df = pd.DataFrame(best_pick_data)
    return best_pick_df

# Flask API to get picks
@app.route('/api/picks', methods=['GET', 'POST', 'OPTIONS'])
def get_picks():
    best_pick_df = fetch_and_compare_odds()  # Fetch picks
    #Replace NAN with None to fix JSON errors
    best_pick_df = best_pick_df.replace({np.nan: None})
    picks = {}
    
    for index, row in best_pick_df.iterrows():
        if pd.notna(row['Best Home Odds']) or pd.notna(row['Best Away Odds']):
            picks[row['Game ID']] = {
                "sport": row['Sport'],
                "home_team": row['Home Team'],
                "away_team": row['Away Team'],
                "best_home_odds": row['Best Home Odds'],
                "best_away_odds": row['Best Away Odds'],
                "best_home_bookmaker": row['Best Home Bookmaker'],
                "best_away_bookmaker": row['Best Away Bookmaker'],
                "line_to_beat_home": row['Line to Beat Home Odds'],
                "line_to_beat_away": row['Line to Beat Away Odds']
            }
    
    


    return jsonify(picks)



# Start Flask app
if __name__ == '__main__':
    app.run()
