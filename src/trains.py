import os
import requests
import json

from requests.auth import HTTPBasicAuth

def abbrStation(journeyConfig, inputStr):
    dict = journeyConfig['stationAbbr']
    for key in dict.keys():
        inputStr = inputStr.replace(key, dict[key])
    return inputStr

def loadDeparturesForStationRTT(journeyConfig, username, password):
    if journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please set the journey.departureStation property in config.json")

    if username == "" or password == "":
        raise ValueError(
            "Please complete the rtt_username and rtt_password sections of your config.json file")

    departureStation = journeyConfig["departureStation"]
    destinationStation = journeyConfig["destinationStation"]
    if (destinationStation == ""):
        URL = f"https://api.rtt.io/api/v1/json/search/{departureStation}"
    else:
        URL = f"https://api.rtt.io/api/v1/json/search/{departureStation}/to/{destinationStation}"
        
    r = requests.get(url=URL, auth=HTTPBasicAuth(username,password))
    data = r.json()

    # Need to abbreviate the station names (perhaps)
    data["location"]["name"] = abbrStation(journeyConfig, data["location"]["name"])
    if "filter" in data and "destination" in data["filter"]:
        data["filter"]["destination"["name"] = abbrStation(journeyConfig, data["filter"]["destination"["name"])
    
    return data["services"], data["location"]["name"]


def loadDeparturesForStation(journeyConfig, appId, apiKey):
    if journeyConfig["departureStation"] == "":
        raise ValueError(
            "Please set the journey.departureStation property in config.json")

    if appId == "" or apiKey == "":
        raise ValueError(
            "Please complete the transportApi section of your config.json file")

    departureStation = journeyConfig["departureStation"]

    URL = f"http://transportapi.com/v3/uk/train/station/{departureStation}/live.json"

    PARAMS = {'app_id': appId,
              'app_key': apiKey,
              'calling_at': journeyConfig["destinationStation"]}

    r = requests.get(url=URL, params=PARAMS)

    data = r.json()
    #apply abbreviations / replacements to station names (long stations names dont look great on layout)
    #see config file for replacement list
    for item in data["departures"]["all"]:
         item['origin_name'] = abbrStation(journeyConfig, item['origin_name'])
         item['destination_name'] = abbrStation(journeyConfig, item['destination_name'])

    if "error" in data:
        raise ValueError(data["error"])

    return data["departures"]["all"], data["station_name"]


def loadDestinationsForDeparture(journeyConfig, timetableUrl):
    r = requests.get(url=timetableUrl)

    data = r.json()

    #apply abbreviations / replacements to station names (long stations names dont look great on layout)
    #see config file for replacement list
    foundDepartureStation = False

    for item in list(data["stops"]):
        if item['station_code'] == journeyConfig['departureStation']:
            foundDepartureStation = True

        if foundDepartureStation == False:
            data["stops"].remove(item)
            continue

        item['station_name'] = abbrStation(journeyConfig, item['station_name'])

    if "error" in data:
        raise ValueError(data["error"])

    departureDestinationList = list(map(lambda x: x["station_name"], data["stops"]))[1:]

    if len(departureDestinationList) == 1:
        departureDestinationList[0] = departureDestinationList[0] + ' only.'

    return departureDestinationList
