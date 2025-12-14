from collections import Counter
from typing import List, Tuple, Optional
from bs4 import BeautifulSoup

import countryflag
import requests
import json
import re
import pickle

"""
PERFORMS ANALSYS OF MUSICIANS AT AN EVENT

STEPS:
1) grab the frame source from "The Band" page on the app
    typically https://app.XXXXXXX.com/en/events/?path=%252Fd%252Fmille.php%253FidEvento%253D178%2526lang%253Den
2) save this html to a local file input.html
3) configure this program
    3a) if you want to use google maps to look up countries of cities, store the key in maps.key
    3b) decide if you want to hit the R1K website when needed for more details on musicians (set allowSiteHits, below)
4) run this program
"""

# global vars
theBand = []
mapsKey = ""
cities = {}
hostCountry = "United Kingdom"
capacity = 400

# whether to allow profile interrogation of R1K website (use with caution!)
allowSiteHits = True


def loadMapsKey():
    try:
        with open("maps.key") as k:
            global mapsKey
            mapsKey = k.read().strip()
    except (FileNotFoundError):
        print(f"No maps.key file found - proceeding without API access...")
        

def lookupCountry(city = "London"):
    # we maintain a dict of city to country mappings
    # faster and cheaper if we don't have to call google
    # maps more than once for each new city
    global cities
    
    if city in cities:
        return cities[city]
    elif mapsKey == "" or city == None:
        # cannot call maps api with no key, so skip it
        # also cannot process if we have no city
        return None
    else:
        # look up from google maps
        url = "https://maps.googleapis.com/maps/api/geocode/json?key=" + mapsKey + "&address=" + city
        r = requests.post(url)
        if r.status_code == 200:
            country = get_country_from_geocoding_json(r.json())
            cities[city] = country
            return country


def get_country_from_geocoding_json(json_data):
    # Extracts the country long_name from a Google Geocoding API JSON response.
    # Check if the results list is present and not empty
    results = json_data.get('results')
    
    if not results:
        return None

    # Usually, the first result (index 0) is the most relevant
    first_result = results[0]
    address_components = first_result.get('address_components', [])

    for component in address_components:
        # Check if 'country' is in the list of types for this component
        if 'country' in component.get('types', []):
            return component.get('long_name')

    return None


def getMusicianPopup(mId):
    url = f"https://legacy-app.rockin1000.com/shared/load_dati_musicista.php?idMusicista={mId}&lang=en"
    r = requests.post(url)
    if r.status_code == 200:
        return r.text
    

def importBand(filename = "input.html", outputBand = True):
    global theBand
    currentSection = ""
    nameNext = False
    musicianName = ""
    city = "unknown"
    country = "unknown"
    
    with open(filename, mode="r", encoding="utf-8") as f:
        html = f.read()

    # extract what we can get from the main page, but it won't be perfect
    prelimBand = extract_musicians_full_data(html)

    # now iterate and fix the locations (city/country)
    count = 0
    for m in prelimBand:
        count += 1
        
        if m[1] == None and allowSiteHits == True:
            # main page has no city, so get it from the pop up
            # we can also get the country this way
            # (but avoid unless necessary to reduce website hits)
            mProfile = extract_musician_profile_data(getMusicianPopup(m[2]))
            city = mProfile[1]
            country = mProfile[2]
            theBand.append((m[3], m[0], city, country))
        else:
            # else we have the city so we need to look up the country
            # this function hits the cache first, then uses google maps as a last resort
            country = lookupCountry(m[1])
            theBand.append((m[3],m[0],m[1],country))
            


def extract_musicians_full_data(html_content: str) -> List[Tuple[str, Optional[str], int, str]]:
    """
    Extracts musician's name, town, ID, and instrument category from the HTML.

    Args:
        html_content: The full HTML content of the band roster page.

    Returns:
        A list of tuples, where each tuple is (Name, Town, ID, Category).
        Town is None if not present.

    NB: Google gemini wrote this.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    musicians_data: List[Tuple[str, Optional[str], int, str]] = []

    # Regex to extract the ID number from the onclick attribute
    id_regex = re.compile(r"apriScheda\((\d+),")

    # Find all main columns (col bg-white mx-1) as they wrap each category
    category_columns = soup.find_all('div', class_='col bg-white mx-1')

    for column in category_columns:
        # 1. Extract the Category Name (instrument)
        # The category is inside an <h4> tag within a p-2 bg-light div
        category_header = column.find('h4')
        if not category_header:
            continue
            
        category_name: str = category_header.get_text(strip=True)

        # Find all musician entries within this column
        for media_div in column.find_all('div', class_='media'):
            # 2. Extract the ID from the onclick event
            onclick_value = media_div.get('onclick', '')
            match = id_regex.search(onclick_value)
            musician_id: Optional[int] = None
            if match:
                musician_id = int(match.group(1))
            
            if musician_id is None:
                continue

            # 3. Extract the Name and Town
            media_body = media_div.find('div', class_='media-body')
            if not media_body:
                continue

            name_tag = media_body.find('strong')
            musician_name: str = name_tag.get_text(strip=True) if name_tag else "Unknown Name"

            # The town is in the optional <small> tag
            town_tag = media_body.find('small')
            musician_town: Optional[str] = None
            if town_tag:
                town_text = town_tag.get_text(strip=True)
                if town_text:
                    musician_town = town_text

            # 4. Add the extracted data to the list
            musicians_data.append((musician_name, musician_town, musician_id, category_name))

    return musicians_data



def extract_musician_profile_data(html_content: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extracts the musician's name, city, country, and instrument from the profile HTML snippet.

    Args:
        html_content: The HTML content of the musician's profile.

    Returns:
        A tuple: (Name, City, Country, Instrument)
        City and Country will be None if the location is not present or cannot be parsed.

    NB: Google gemini wrote this.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Regex to parse 'City (Country)' format. It captures two groups:
    # 1. The City (any text before the first opening parenthesis)
    # 2. The Country (any text inside the parentheses)
    location_regex = re.compile(r"([^()]+)\s*\(([^()]+)\)")

    # 1. Extract Name
    name_tag = soup.find('h2', class_='sezione-head')
    name = name_tag.get_text(strip=True) if name_tag else None

    # 2. Extract Location string (e.g., "Manchester (United Kingdom)")
    location_tag = soup.find('div', class_='col-12').find('p')
    location_str: Optional[str] = location_tag.get_text(strip=True) if location_tag else None

    city: Optional[str] = None
    country: Optional[str] = None

    if location_str:
        # Try to match the regex pattern
        match = location_regex.search(location_str)
        if match:
            # Group 1 is the city, Group 2 is the country
            city = match.group(1).strip()
            country = match.group(2).strip()
        else:
            # If the format is just a city name (e.g., "Bologna"), assign it to city
            city = location_str

    # 3. Extract Instrument/Role
    role_tag = soup.find('big')
    instrument = role_tag.get_text(strip=True) if role_tag else None

    # Return the new tuple format
    return (name, city, country, instrument)

def printBand():
    for m in theBand:
        print(m)


def summariseBand():
    # summarise instrument categories
    cats = Counter(elem[0] for elem in theBand)
    print("\nInstrument Catgories")
    for c in cats:
        if c == "Guitar":
            print('\U0001F3B8',end=" ")
        if c == "Bass":
            print('\U0001F3B8',end=" ")
        if c == "Drums":
            print('\U0001F941',end=" ")
        if c == "Voice":
            print('\U0001F3A4',end=" ")
        if c == "Keyboards":
            print('\U0001F3B9',end=" ")
        print(f"{c}: {cats[c]}")
        

    # summarise countries (pays, for short ;-)
    pays = Counter(elem[3] for elem in theBand)
    print("\nCountries")
    local = 0
    international = 0
    total = 0
    
    for p in pays:
        if p != None:
            flag = countryflag.getflag(p)
        else:
            flag = ""


        # summarise local vs int
        if p == hostCountry:
            local += pays[p]
        else:
            international += pays[p]
        total += pays[p]
        
        print(f"{flag} {p}: {pays[p]}")

    print(f"\nTotals:\nLocal: {local} ({int(local/total*100)}%) International: {international} ({int(international/total*100)}%)\n{total}/{capacity} Confirmed Musicians.")
    print(f"Local quota {int(local/(capacity*0.75)*100)}% filled; International quota {int(international/(capacity*0.25)*100)}% filled (assumes 75% locals)")

# warm the cache of city:country mappings so we don't have to ask Google Maps each time
def loadCountries(filename = "countries.pkl"):
    global cities
    
    with open(filename, 'rb') as f:
        cities = pickle.load(f)

# save the (maybe improved) cache for next time
def saveCountries(filename = "countries.pkl"):
    with open(filename, 'wb') as f:
        pickle.dump(cities, f)
    

# main steps 
loadCountries()     # load the city to countries cache
loadMapsKey()       # load the google maps key
importBand()        # import the band data (cut and paste from the web page)
saveCountries()     # save the cache back to disk
printBand()
summariseBand()     # summarise the band




