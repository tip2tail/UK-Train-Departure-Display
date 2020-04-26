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

# Declare Variables for Global
# ============================================================================================
stationRenderCount = 0
pauseCount = 0
isRtt = False

# Routines
# ============================================================================================

def icon(name):
    switcher = {
        'clock': u'\uf017',
        'bus': u'\uf55e',
        'train': u'\uf238',
        'subway': u'\uf239',
    }
    value = switcher.get(name, None)
    if (value == None):
        raise ValueError("Invalid icon name requested")
    return value


def getLogDirPath():
    homeDir = expanduser("~")
    logPath = f"{homeDir}/logs/piDepartures"
    Path(logPath).mkdir(parents=True, exist_ok=True)
    return logPath


def tidyLogFiles():
    logDir = getLogDirPath()
    listFiles = os.listdir(logDir)
    fullPath = [f"{logDir}/{x}" for x in listFiles]
    fullPath.sort(key=os.path.getctime)

    # We want to keep 14 files
    fileCount = len(listFiles)
    removeFileCount = fileCount - 14
    removeIndex = 0
    while removeIndex < (removeFileCount - 1):
        pop = fullPath.pop(removeIndex)
        os.remove(pop)
        removeIndex += 1


def getYMD():
    return datetime.today().strftime('%Y-%m-%d')


def openLogFile():
    global logFileDate
    global isDebugMode
    global logger

    # Remove old files
    tidyLogFiles()

    logFileDate = getYMD()
    logPath = f'{getLogDirPath()}/{logFileDate}.log'

    if (len(sys.argv) > 1 and sys.argv[1] == 'debug'):
        isDebugMode = True
        logLevel = logging.DEBUG
    else:
        logLevel = logging.WARNING

    fileh = logging.FileHandler(logPath, 'a')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fileh.setFormatter(formatter)
    fileh.setLevel(logLevel)

    logger = logging.getLogger('piDepartures')      # piDepartures logger
    for hdlr in logger.handlers[:]:   # Remove all old handlers
        logger.removeHandler(hdlr)
    logger.addHandler(fileh)          # Set the new handler
    logger.setLevel(logLevel)


def log(heading, message, isError=False):
    global logFileDate
    global logger

    if (logFileDate != getYMD()):
        # Need to reopen the log file
        openLogFile()

    if (isError):
        logger.error(f'{heading} -- {message}')
    else:
        logger.debug(f'{heading} -- {message}')


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
        headcode = ""
        if config['showHeadcode'] == True:
            headcode = f" ({departure['trainIdentity']})"
        departureTime = convertRttTime(locDetail["gbttBookedDeparture"])
        destinationName = f"{locDetail['destination'][0]['description']}{headcode}"
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
                hasRealtimeDeparture = False
                if "realtimeDeparture" in locDetail:
                    hasRealtimeDeparture = True

                if hasRealtimeDeparture and isinstance(locDetail["realtimeDeparture"], str):
                    train = 'Exp ' + convertRttTime(locDetail["realtimeDeparture"])

                if not hasRealtimeDeparture or locDetail["gbttBookedDeparture"] == locDetail["realtimeDeparture"]:
                    train = "On time"

        else:
            if departure["status"] == "CANCELLED":
                train = "Cancelled"
            else:
                if isinstance(departure["expected_departure_time"], str):
                    train = 'Exp '+departure["expected_departure_time"]

                if departure["aimed_departure_time"] == departure["expected_departure_time"]:
                    train = "On time"

        w, _unused_h = draw.textsize(train, font)
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
        global stationRenderCount
        global pauseCount
        
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
    global isRtt
    global isDebugMode

    rawTime = datetime.now().time()
    hour, minute, second = str(rawTime).split('.')[0].split(':')

    dataSource = ''
    if isDebugMode:
        if isRtt:
            dataSource = 'RTT: '
        else:
            dataSource = 'tAPI: '

    w3, _unused_h3 = draw.textsize(f"{icon('clock')} ", fontAwesomeSmall)
    w1, _unused_h1 = draw.textsize(f" {dataSource}{hour}:{minute}", fontBoldLarge)
    w2, _unused_h2 = draw.textsize(":00", fontBoldTall)

    draw.text(((width - w1 - w2 - w3) / 2, 0), text=f"{icon('clock')} ",
            font=fontAwesomeSmall, fill="yellow")
    draw.text((((width - w1 - w2 - w3) / 2) + w3, 0), text=f"{dataSource}{hour}:{minute}",
            font=fontBoldLarge, fill="yellow")
    draw.text((((width - w1 - w2 - w3) / 2) + (w1 + w3), 5), text=f":{second}",
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
    if departures == None or len(departures) == 0:
        return False, False, stationName

    if isRtt:
        serviceUid = departures[0]["serviceUid"]
        serviceDate = departures[0]["runDate"].replace("-","/")

        firstDepartureDestinations = loadDestinationsForDepartureRtt(
            journeyConfig, serviceUid, serviceDate, apiConfig["rttUsername"], apiConfig["rttPassword"], config["showTOC"])

    else:
        firstDepartureDestinations = loadDestinationsForDeparture(
            journeyConfig, departures[0]["service_timetable"]["id"])

    return departures, firstDepartureDestinations, stationName


def drawBlankSignage(device, width, height, departureStation):
    global stationRenderCount
    global pauseCount

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
    global stationRenderCount
    global pauseCount

    device.clear()

    virtualViewport = viewport(device, width=width, height=height)

    status = "Exp 00:00"
    callingAt = "Calling at:"

    departures, firstDepartureDestinations, departureStation = data

    log("departures", departures)
    log("firstDepartureDestinations", firstDepartureDestinations)
    log("departureStation", departureStation)

    with canvas(device) as draw:
        w, _unused_h = draw.textsize(callingAt, font)

    callingWidth = w
    width = virtualViewport.width

    # Measure the text size
    with canvas(device) as draw:
        w, h = draw.textsize(status, font)
        pw, _unused_ph = draw.textsize("Plat 88", font)

    # Destination
    rowOneA = snapshot(
        width - w - pw - 5, 10, renderDestination(departures[0], fontBold), interval=10)
    # On Time / Exp
    rowOneB = snapshot(w, 10, renderServiceStatus(
        departures[0]), interval=1)
    # Platform
    rowOneC = snapshot(pw, 10, renderPlatform(departures[0]), interval=10)
    # Calling at:
    rowTwoA = snapshot(callingWidth, 10, renderCallingAt, interval=100)
    # Scrolling stations
    rowTwoB = snapshot(width - callingWidth, 10,
                       renderStations(", ".join(firstDepartureDestinations)), interval=0.01)

    # 2nd Departure
    if(len(departures) > 1):
        rowThreeA = snapshot(width - w - pw, 10, renderDestination(
            departures[1], font), interval=10)
        rowThreeB = snapshot(w, 10, renderServiceStatus(
            departures[1]), interval=1)
        rowThreeC = snapshot(pw, 10, renderPlatform(departures[1]), interval=10)

    # 3rd Departure
    if(len(departures) > 2):
        rowFourA = snapshot(width - w - pw, 10, renderDestination(
            departures[2], font), interval=10)
        rowFourB = snapshot(w, 10, renderServiceStatus(
            departures[2]), interval=1)
        rowFourC = snapshot(pw, 10, renderPlatform(departures[2]), interval=10)

    # Big Clock
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


def convertRttTime(timeIn):
    timeOut = f'{timeIn[0:2]}:{timeIn[2:4]}'
    return timeOut


# Main program
# ============================================================================================
try:

    # Debug mode off by default, start the logfile
    isDebugMode = False
    logFileDate = None
    logger = None
    openLogFile()
    log("STARTUP","================================")
    log("STARTUP","New piDepartures Session Started")
    log("STARTUP","================================")

    # Load the cofig files
    config = loadConfig()

    serial = spi()
    device = ssd1322(serial, mode="1", rotate=2)
    font = makeFont("Dot Matrix Regular.ttf", 10)
    fontBold = makeFont("Dot Matrix Bold.ttf", 10)
    fontBoldTall = makeFont("Dot Matrix Bold Tall.ttf", 10)
    fontBoldLarge = makeFont("Dot Matrix Bold.ttf", 20)
    fontAwesomeSmall = makeFont("FontAwesome.otf", 10)
    fontAwesomeLarge = makeFont("FontAwesome.otf", 20)

    widgetWidth = 256
    widgetHeight = 64

    stationRenderCount = 0
    pauseCount = 0
    isRtt = (config['transportApi']['apiType'] == "RTT")
    if isRtt:
        log("SOURCE", "Using RealtimeTrains API")
    else:
        log("SOURCE", "Using TransportApi")

    regulator = framerate_regulator(fps=10)

    data = loadData(config['transportApi'], config['journey'])
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
            if(timeNow - timeAtStart >= config['refreshTime']):
                log("REFRESH", f"Full Refresh after {config['refreshTime']} seconds")

                data = loadData(config['transportApi'], config['journey'])
                if data[0] == False:
                    virtual = drawBlankSignage(
                        device, width=widgetWidth, height=widgetHeight, departureStation=data[2])
                else:
                    virtual = drawSignage(device, width=widgetWidth,
                                          height=widgetHeight, data=data)

                timeAtStart = time.time()

            timeNow = time.time()
            virtual.refresh()

except KeyboardInterrupt:
    pass
except ValueError as err:
    log("VALUE_ERROR", err)
    print(f"Error: {err}")
except KeyError as err:
    log("KEY_ERROR", err)
    print(f"Error: Please ensure the {err} configuration value is set in config.json.")
