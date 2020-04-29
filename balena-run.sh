#!/bin/bash

# Creates a config.json file based on the ENV variables set in the balena interface for your app/device
if [ ! -f config.json ]; then
  cp config.sample.json config.json
  jq .journey.departureStation=\""${departureStation}"\" config.json | sponge config.json
  jq .journey.destinationStation=\""${destinationStation}"\" config.json | sponge config.json
  jq .journey.outOfHoursName=\""${outOfHoursName}"\" config.json | sponge config.json
  jq .refreshTime="${refreshTime}" config.json | sponge config.json
  jq .transportApi.appId=\""${transportApi_appId}"\" config.json | sponge config.json
  jq .transportApi.apiKey=\""${transportApi_apiKey}"\" config.json | sponge config.json
  jq .transportApi.operatingHours=\""${transportApi_operatingHours}"\" config.json | sponge config.json
  jq .transportApi.apiType=\""${transportApi_apiType}"\" config.json | sponge config.json
  jq .transportApi.rttUsername=\""${transportApi_rttUsername}"\" config.json | sponge config.json
  jq .showHeadcode=\""${showHeadcode}"\" config.json | sponge config.json
  jq .showTOC=\""${showTOC}"\" config.json | sponge config.json
fi

# Run the application
python ./src/main.py
