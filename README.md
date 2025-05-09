# WiiboardCsvMaker
640hz multithreaded reader for alliterated wiiboard 

install requirements txt connect to the wii board via usb c

4 main runnable scripts

calibration, one sensor at the time, run enter weight in kg being placed on the sensor, wait 5-10 seconds press enter move on to the next weight stating its weight again, once all weights have been done press enter without entering weight and the file will be saved. Naming convetion of the files TL top left panel/sensor next to the wii logo TR top right panel/sensor next to the wii logo, BL and BR bottom left and right.

if you want to save a csv file to be elaborated later on use readandsavecsv.py if u want to observe in realtime use readandobserverealtime.

if u want to see the plots from the savecsv use plotData.
