import datetime
import time
import requests
import RPi.GPIO as GPIO
from time import sleep
from gpiozero import MCP3008
import threading

# Constants
IR_THRESHOLD = 0.1
MICROPHONE_THRESHOLD = 0.65
CHECK_DATABASE_INTERVAL = 1
ROUTINE_CHECK_INTERVAL = 10

# Global variables
url = "https://studev.groept.be/api/a22ib2b07/CheckColour"
current_pwm_value = 0
colour_values = [255, 255, 255]
storedIntensity = 100
credentials = ('a22ib2b07', 'secret')
threshold_irSensor = 0.1
redPin = 12
greenPin = 19
bluePin = 13
active_routines = []
routine_stop_events = {}
lock = threading.Lock()
database_interval_event = threading.Event()
routine_interval_event = threading.Event()

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
    redPin_pwm.ChangeDutyCycle(0)
    greenPin_pwm.ChangeDutyCycle(0)
    bluePin_pwm.ChangeDutyCycle(0)

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
        try:
            infrared_value = infrared.value
            if infrared_value > IR_THRESHOLD:
                for _ in range(10):
                    time.sleep(0.05)
                    if infrared.value < IR_THRESHOLD:
                        door_close = False
                        break
                    else:
                        door_close = True
            if not door_close and previous_door_close:
                toggle_light()
                requests.get("https://studev.groept.be/api/a22ib2b07/SaveSensorTime/Light")
        except Exception as e:
            print(f"Error in check_ir_sensor: {e}")
        finally:
            previous_door_close = door_close


def check_database():
    global colour_values, stored_intensity
    while True:
        try:
            response = requests.get(url)
            values = [response.json()[0]['R'], response.json()[0]['G'], response.json()[0]['B']]
            with lock:
                if values != colour_values:
                    colour_values = values
                    update_colour(colour_values, stored_intensity)
                intensity = response.json()[0]['intensity']
                if intensity != stored_intensity:
                    stored_intensity = intensity
                    update_colour(colour_values, stored_intensity)

                routines_response = requests.get('https://studev.groept.be/api/a22ib2b07/GetStoredRoutines')
                with lock:
                    for routine in routines_response.json():
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
                            routine_thread = threading.Thread(
                                target=run_routine,
                                args=(start_time, stop_time, r, g, b, intensity, routine_stop_events[name])
                            )
                            routine_thread.start()

                    # Check if routines are still in the database, if not remove them from active_routines and stop the thread
                    for routine in active_routines.copy():
                        if routine not in routines_response.json():
                            active_routines.remove(routine)
                            routine_stop_events[name].set()

            database_interval_event.set()
            database_interval_event.clear()
        except Exception as e:
            print(f"Error in check_database: {e}")

        # Wait for the event to be set or until the timeout
        database_interval_event.wait(timeout=CHECK_DATABASE_INTERVAL)



def check_microphone():
    while True:
        try:
            if microphone.value < MICROPHONE_THRESHOLD:
                time.sleep(0.1)
                start_time = time.time()
                while time.time() - start_time < 1:
                    if microphone.value < MICROPHONE_THRESHOLD:
                        toggle_light()
                        requests.get("https://studev.groept.be/api/a22ib2b07/SaveSensorTime/Microphone")
                        print("Microphone toggled light")
        except Exception as e:
            print(f"Error in check_microphone: {e}")


def toggle_light():
    if GPIO.input(redPin) == 1 or GPIO.input(greenPin) == 1 or GPIO.input(bluePin) == 1:
        turn_pwm_off()
    else:
        update_colour(colour_values, storedIntensity)
  

def run_routine(start_time, stop_time, r, g, b, intensity, stop_event):
    try:
        now = datetime.datetime.now().time()
        current_date = datetime.date.today()
        last_run_start = current_date - datetime.timedelta(days=1) if start_time > now else current_date
        last_run_stop = current_date - datetime.timedelta(days=1) if stop_time > now else current_date

        while not stop_event.is_set():
            now = datetime.datetime.now().time()
            current_date = datetime.date.today()

            if start_time <= now:
                if current_date > last_run_start:
                    update_colour([r, g, b], intensity)
                    last_run_start = current_date
                    print("Routine started light")

            if stop_time <= now:
                if current_date > last_run_stop:
                    turn_pwm_off()
                    last_run_stop = current_date
                    print("Routine stopped light")

            routine_interval_event.set()
            routine_interval_event.clear()

            # Wait for the event to be set or until the timeout
            routine_interval_event.wait(timeout=ROUTINE_CHECK_INTERVAL)
    except Exception as e:
        print(f"Error in run_routine: {e}")
        
sensor_thread = threading.Thread(target=check_ir_sensor)
database_thread = threading.Thread(target=check_database)
microphone_thread = threading.Thread(target=check_microphone)

sensor_thread.start()
database_thread.start()
microphone_thread.start()
