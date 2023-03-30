import datetime
import time
import requests
import RPi.GPIO as GPIO
from time import sleep
from gpiozero import MCP3008
import threading

# Global variables
url = "https://studev.groept.be/api/a22ib2b07/CheckColour"
current_pwm_value = 0
colour_values = [255, 255, 255]
storedIntensity = 100
credentials = ('a22ib2b07', 'secret')
threshold_irSensor = 0.95
redPin = 12
greenPin = 19
bluePin = 13
active_routines = []
routine_stop_events = {}

# Set up the GPIO pins
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(redPin, GPIO.OUT)
GPIO.setup(greenPin, GPIO.OUT)
GPIO.setup(bluePin, GPIO.OUT)
infrared = MCP3008(channel=0)
microphone = MCP3008(channel=1)

redPin_pwm = GPIO.PWM(redPin, 255)
greenPin_pwm = GPIO.PWM(greenPin, 255)
bluePin_pwm = GPIO.PWM(bluePin, 255)
redPin_pwm.start(0)
greenPin_pwm.start(0)
bluePin_pwm.start(0)


def turn_pwm_off():
    set_rgb_intensity(0)


def set_rgb_intensity(percentage):
    global current_pwm_value
    if percentage < 0 or percentage > 100:
        print("Invalid percentage value. Must be between 0 and 100.")
        return
    else:
        current_pwm_value = percentage  # Update global variable
        redPin_pwm.ChangeDutyCycle(percentage)
        greenPin_pwm.ChangeDutyCycle(percentage)
        bluePin_pwm.ChangeDutyCycle(percentage)


def update_colour(colour_v, intensity):
    if intensity < 0:
        intensity = 0
    elif intensity > 100:
        intensity = 100
    redPin_pwm.ChangeDutyCycle(colour_v[0] * intensity / 255)
    greenPin_pwm.ChangeDutyCycle(colour_v[1] * intensity / 255)
    bluePin_pwm.ChangeDutyCycle(colour_v[2] * intensity / 255)


def check_ir_sensor():
    door_close = True
    previous_door_close = False
    while True:
        # print("Infrared meter value:", infrared.value)

        if infrared.value > threshold_irSensor:
            for i in range(10):
                sleep(0.05)
                if infrared.value < threshold_irSensor:
                    door_close = False
                    break
                else:
                    door_close = True
        if door_close == False and previous_door_close == True:
            toggle_light()
            requests.get("https://studev.groept.be/api/a22ib2b07/SaveSensorTime/Light")
        previous_door_close = door_close



def check_database():
    global colour_values, storedIntensity, name
    while True:
        response = requests.get('https://studev.groept.be/api/a22ib2b07/CheckColour')
        values = [response.json()[0]['R'], response.json()[0]['G'], response.json()[0]['B']]
        if values != colour_values:
            colour_values = values
            update_colour(colour_values, storedIntensity)
        intensity = response.json()[0]['intensity']
        if intensity != storedIntensity:
            storedIntensity = intensity
            set_rgb_intensity(storedIntensity)


        response = requests.get('https://studev.groept.be/api/a22ib2b07/GetStoredRoutines')
        for i in range(len(response.json())):
            #check if all routines are in list active_routines, if not add them
            routine = response.json()[i]
            if routine not in active_routines:
                active_routines.append(routine)
                name = routine['name']
                start_time = datetime.datetime.strptime(routine['startTime'], "%H:%M:%S").time()
                stop_time = datetime.datetime.strptime(routine['stopTime'], "%H:%M:%S").time()
                r = routine['R']
                g = routine['G']
                b = routine['B']
                intensity = routine['intensity']
                routine_stop_events[name] = threading.Event()
                routine_thread = threading.Thread(target=run_routine, args=(start_time, stop_time, r, g, b, intensity, routine_stop_events[name]))
                routine_thread.start()

        #check if all routines are still in the database, if not remove them from active_routines and stop the thread
        for i in range(len(active_routines)):
            if active_routines[i] not in response.json():
                active_routines.remove(active_routines[i])
                routine_stop_events[name].set()

        # print(active_routines)
        sleep(1)  # Wait 1 second before checking again



def check_microphone():
    while True:
        # if microphone.value < 0.65 2 times in less than a second then toggle the light intensity
        if microphone.value < 0.65:
            sleep(0.1)
            start_time = time.time()
            while time.time() - start_time < 1:
                if microphone.value < 0.65:
                    toggle_light()
                    requests.get("https://studev.groept.be/api/a22ib2b07/SaveSensorTime/Microphone")


def toggle_light():
    if GPIO.input(redPin) == 1 or GPIO.input(greenPin) == 1 or GPIO.input(bluePin) == 1:
        turn_pwm_off()
    else:
        update_colour(colour_values, storedIntensity)

def run_routine(start_time,stop_time, r, g, b, intensity, stop_event):

    #check if the start/stop time is in the past, if so set the last run start/stop to today, so it will not run for today
    now = datetime.datetime.now().time()
    current_date = datetime.date.today()
    if start_time <= now:
        last_run_start = current_date
    else:
        last_run_start = current_date - datetime.timedelta(days=1)
    if stop_time <= now:
        last_run_stop = current_date
    else:
        last_run_stop = current_date - datetime.timedelta(days=1)

    while not stop_event.is_set():
        # print("Thread running" ,stop_event)
        now = datetime.datetime.now().time()
        current_date = datetime.date.today()
        if start_time <= now:
            if current_date > last_run_start:
                update_colour([r, g, b], intensity)
                last_run_start = current_date
        if stop_time <= now:
            if current_date > last_run_stop:
                turn_pwm_off()
                last_run_start = current_date
        sleep(10)  # Wait 10 seconds before checking again


sensor_thread = threading.Thread(target=check_ir_sensor)
database_thread = threading.Thread(target=check_database)
microphone_thread = threading.Thread(target=check_microphone)

sensor_thread.start()
database_thread.start()
microphone_thread.start()
