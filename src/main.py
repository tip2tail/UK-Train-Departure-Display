import os
import sys
import time
import json
import logging

from datetime import timedelta
from timeloop import Timeloop
from datetime import datetime
from PIL import ImageFont, Image
from os.path import expanduser
from pathlib import Path

from trains import loadDeparturesForStation, loadDestinationsForDeparture, loadDeparturesForStationRtt, loadDestinationsForDepartureRtt

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.oled.device import ssd1322
from luma.core.virtual import viewport, snapshot
from luma.core.sprite_system import framerate_regulator

from open import isRun

def log(heading, message, isError=False):
    if (isError):
        logging.error(heading)
        logging.error(message)
        logging.error("===========================")
    else:
        logging.debug(heading)
        logging.debug(message)
        logging.debug("===========================")

def loadConfig():
    with open('config.json', 'r') as jsonConfig:
        data = json.load(jsonConfig)
        return data

def makeFont(name, size):
    font_path = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            'fonts',
            name
        )
    )
    return ImageFont.truetype(font_path, size)


def renderDestination(departure, font):
    global isRtt

    if isRtt:
        locDetail = departure["locationDetail"]
        departureTime = locDetail["gbttBookedDeparture"]
        destinationName = locDetail["destination"][0]["description"]
    else:
        departureTime = departure["aimed_departure_time"]
        destinationName = departure["destination_name"]

    def drawText(draw, width, height):
        train = f"{departureTime}  {destinationName}"
        draw.text((0, 0), text=train, font=font, fill="yellow")

    return drawText


def renderServiceStatus(departure):
    def drawText(draw, width, height):
        global isRtt
        train = ""

        if isRtt:
            locDetail = departure["locationDetail"]

            if "cancelReasonCode" in locDetail and isinstance(locDetail["cancelReasonCode"], str):
                train = "Cancelled"
            else:
                if "realtimeDeparture" in locDetail and isinstance(locDetail["realtimeDeparture"], str):
                    train = 'Exp ' + locDetail["realtimeDeparture"]

                if locDetail["gbttBookedDeparture"] == locDetail["realtimeDeparture"]:
                    train = "On time"

        else:
            if departure["status"] == "CANCELLED":
                train = "Cancelled"
            else:
                if isinstance(departure["expected_departure_time"], str):
                    train = 'Exp '+departure["expected_departure_time"]

                if departure["aimed_departure_time"] == departure["expected_departure_time"]:
                    train = "On time"

        w, h = draw.textsize(train, font)
        draw.text((width-w,0), text=train, font=font, fill="yellow")
    return drawText


def renderPlatform(departure):
    def drawText(draw, width, height):
        global isRtt

        if isRtt:
            log("serviceType", departure["serviceType"])
            log("locationDetail", departure["locationDetail"])
            if departure["serviceType"] == "bus":
                draw.text((0, 0), text="BUS", font=font, fill="yellow")
            else:
                if "platform" in departure["locationDetail"] and isinstance(departure["locationDetail"]["platform"], str):
                    draw.text((0, 0), text="Plat "+departure["locationDetail"]["platform"], font=font, fill="yellow")
        else:
            if departure["mode"] == "bus":
                draw.text((0, 0), text="BUS", font=font, fill="yellow")
            else:
                if isinstance(departure["platform"], str):
                    draw.text((0, 0), text="Plat "+departure["platform"], font=font, fill="yellow")
        
    return drawText


def renderCallingAt(draw, width, height):
    stations = "Calling at:"
    draw.text((0, 0), text=stations, font=font, fill="yellow")


def renderStations(stations):
    def drawText(draw, width, height):
        global stationRenderCount, pauseCount
        pauseCount = 0

        if(len(stations) == stationRenderCount - 5):
            stationRenderCount = 0

        draw.text(
            (0, 0), text=stations[stationRenderCount:], width=width, font=font, fill="yellow")

        if stationRenderCount == 0 and pauseCount < 8:
            pauseCount += 1
            stationRenderCount = 0
        else:
            pauseCount = 0
            stationRenderCount += 1

    return drawText

def renderTime(draw, width, height):
    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')

    w1, h1 = draw.textsize("{}:{}".format(hour, minute), fontBoldLarge)
    w2, h2 = draw.textsize(":00", fontBoldTall)

    draw.text(((width - w1 - w2) / 2, 0), text="{}:{}".format(hour, minute),
              font=fontBoldLarge, fill="yellow")
    draw.text((((width - w1 - w2) / 2) + w1, 5), text=":{}".format(second),
              font=fontBoldTall, fill="yellow")


def renderWelcomeTo(xOffset):
    def drawText(draw, width, height):
        text = "Welcome to"
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return drawText


def renderDepartureStation(departureStation, xOffset):
    def draw(draw, width, height):
        text = departureStation
        draw.text((int(xOffset), 0), text=text, font=fontBold, fill="yellow")

    return draw


def renderDots(draw, width, height):
    text = ".  .  ."
    draw.text((0, 0), text=text, font=fontBold, fill="yellow")


def loadData(apiConfig, journeyConfig):
    global isRtt

    runHours = [int(x) for x in apiConfig['operatingHours'].split('-')]
    if isRun(runHours[0], runHours[1]) == False:
        return False, False, journeyConfig['outOfHoursName']

    if isRtt:
        departures, stationName = loadDeparturesForStationRtt(
            journeyConfig, apiConfig["rttUsername"], apiConfig["rttPassword"])
    else:
        departures, stationName = loadDeparturesForStation(
            journeyConfig, apiConfig["appId"], apiConfig["apiKey"])

    # No departures due! Display the "Welcome To..." message
    if len(departures) == 0:
        return False, False, stationName

    if isRtt:
        serviceUid = departures[0]["serviceUid"]
        serviceDate = departures[0]["runDate"].replace("-","/")

        firstDepartureDestinations = loadDestinationsForDepartureRtt(
            journeyConfig, serviceUid, serviceDate, apiConfig["rttUsername"], apiConfig["rttPassword"])

    else:
        firstDepartureDestinations = loadDestinationsForDeparture(
            journeyConfig, departures[0]["service_timetable"]["id"])

    return departures, firstDepartureDestinations, stationName


def drawBlankSignage(device, width, height, departureStation):
    global stationRenderCount, pauseCount

    with canvas(device) as draw:
        welcomeSize = draw.textsize("Welcome to", fontBold)

    with canvas(device) as draw:
        stationSize = draw.textsize(departureStation, fontBold)

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    rowOne = snapshot(width, 10, renderWelcomeTo(
        (width - welcomeSize[0]) / 2), interval=10)
    rowTwo = snapshot(width, 10, renderDepartureStation(
        departureStation, (width - stationSize[0]) / 2), interval=10)
    rowThree = snapshot(width, 10, renderDots, interval=10)
    rowTime = snapshot(width, 14, renderTime, interval=1)

    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    virtualViewport.add_hotspot(rowOne, (0, 0))
    virtualViewport.add_hotspot(rowTwo, (0, 12))
    virtualViewport.add_hotspot(rowThree, (0, 24))
    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport


def drawSignage(device, width, height, data):
    global stationRenderCount, pauseCount

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    status = "Exp 00:00"
    callingAt = "Calling at:"

    departures, firstDepartureDestinations, departureStation = data
    logging.info("firstDepartureDestinations")
    logging.info(firstDepartureDestinations)
    # logging.warning(firstDepartureDestinations)

    with canvas(device) as draw:
        w, h = draw.textsize(callingAt, font)

    callingWidth = w
    width = virtualViewport.width

    # First measure the text size
    with canvas(device) as draw:
        w, h = draw.textsize(status, font)
        pw, ph = draw.textsize("Plat 88", font)

    rowOneA = snapshot(
        width - w - pw - 5, 10, renderDestination(departures[0], fontBold), interval=10)
    rowOneB = snapshot(w, 10, renderServiceStatus(
        departures[0]), interval=1)
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    rowTwoB = snapshot(width - callingWidth, 10,
                       renderStations(", ".join(firstDepartureDestinations)), interval=0.1)

    if(len(departures) > 1):
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(
            departures[1], font), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(
            departures[1]), interval=1)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)

    if(len(departures) > 2):
        rowFourA = snapshot(width - w - pw, 10, renderDestination(
            departures[2], font), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(
            departures[2]), interval=1)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2]), interval=10)

    rowTime = snapshot(width, 14, renderTime, interval=0.1)

    if len(virtualViewport._hotspots) > 0:
        for hotspot, xy in virtualViewport._hotspots:
            virtualViewport.remove_hotspot(hotspot, xy)

    stationRenderCount = 0
    pauseCount = 0

    virtualViewport.add_hotspot(rowOneA, (0, 0))
    virtualViewport.add_hotspot(rowOneB, (width - w, 0))
    virtualViewport.add_hotspot(rowOneC, (width - w - pw, 0))
    virtualViewport.add_hotspot(rowTwoA, (0, 12))
    virtualViewport.add_hotspot(rowTwoB, (callingWidth, 12))

    if(len(departures) > 1):
        virtualViewport.add_hotspot(rowThreeA, (0, 24))
        virtualViewport.add_hotspot(rowThreeB, (width - w, 24))
        virtualViewport.add_hotspot(rowThreeC, (width - w - pw, 24))

    if(len(departures) > 2):
        virtualViewport.add_hotspot(rowFourA, (0, 36))
        virtualViewport.add_hotspot(rowFourB, (width - w, 36))
        virtualViewport.add_hotspot(rowFourC, (width - w - pw, 36))

    virtualViewport.add_hotspot(rowTime, (0, 50))

    return virtualViewport


try:

    # Start the logging
    homeDir = expanduser("~")
    Path(f"{homeDir}/logs/trains").mkdir(parents=True, exist_ok=True)
    logPath = f'{homeDir}/logs/trains/train-display.log'
    if (len(sys.argv) > 1 and sys.argv[1] == 'debug'):
        logging.basicConfig(filename=logPath, level=logging.DEBUG)
    else:
        logging.basicConfig(filename=logPath, level=logging.WARNING)

    # Load the cofig files
    config = loadConfig()

    serial = spi()
    device = ssd1322(serial, mode="1", rotate=2)
    font = makeFont("Dot Matrix Regular.ttf", 10)
    fontBold = makeFont("Dot Matrix Bold.ttf", 10)
    fontBoldTall = makeFont("Dot Matrix Bold Tall.ttf", 10)
    fontBoldLarge = makeFont("Dot Matrix Bold.ttf", 20)

    widgetWidth = 256
    widgetHeight = 64

    stationRenderCount = 0
    pauseCount = 0
    loop_count = 0
    isRtt = (config["transportApi"]['apiType'] == "RTT")

    regulator = framerate_regulator(fps=10)

    data = loadData(config["transportApi"], config["journey"])
    if data[0] == False:
        virtual = drawBlankSignage(
            device, width=widgetWidth, height=widgetHeight, departureStation=data[2])
    else:
        virtual = drawSignage(device, width=widgetWidth,
                            height=widgetHeight, data=data)
        

    timeAtStart = time.time()
    timeNow = time.time()

    while True:
        with regulator:
            if isRtt:
                a = 1
            else:
                if data[0] == False:
                    virtual = drawBlankSignage(
                        device, width=widgetWidth, height=widgetHeight, departureStation=data[2])
                else:
                    virtual = drawSignage(device, width=widgetWidth,
                                        height=widgetHeight, data=data)

            timeNow = time.time()
            virtual.refresh()

except KeyboardInterrupt:
    pass
except ValueError as err:
    print(f"Error: {err}")
except KeyError as err:
    print(f"Error: Please ensure the {err} configuration value is set in config.json.")
