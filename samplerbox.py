#  SamplerBox - Open-Source Sampler
#
#  Author:    Joseph Ernest (@JosephErnest)
#  Website:   http://www.samplerbox.org/
#  License:   Creative Commons ShareAlike 3.0
#             (http://creativecommons.org/licenses/by-sa/3.0/)
#
#  Main script for SamplerBox (requires Python 3.7 or higher).
#  Handles MIDI input, audio output, and sample management.

#########################################
# IMPORT REQUIRED MODULES
#########################################


import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from config import *
import wave
import time
import numpy
import sounddevice

import re


import threading
import struct
import rtmidi_python as rtmidi
import samplerbox_audio

import builtins  # Ensure access to built-in functions

#########################################
# CUSTOM WAV READER TO HANDLE CUE & LOOP MARKERS
#########################################

class waveread(wave.Wave_read):
    def __init__(self, file):
        if not isinstance(file, (str, bytes, os.PathLike)):
            raise TypeError(f"Expected a file path, got {type(file)} instead: {file}")

        with open(file, "rb") as f:
            header = f.read(44)  # Read first 44 bytes
            print(f"DEBUG: Full WAV header (raw read) = {header}")

            if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                raise IOError(f'Invalid WAVE file, header: {header}')

        super().__init__(file)  # ✅ Open the file properly

    def getloops(self):
        """ Return loop points if they exist, otherwise return None """
        return None  # ✅ Temporary fix: No loop points are being read



#########################################
# SAMPLE PROCESSING AND SOUND LOADING
#########################################

class Sound:
    def __init__(self, filename, midinote, velocity):
        self.fname = filename
        self.midinote = midinote
        self.velocity = velocity

        # ✅ Ensure filename is a string before passing to waveread
        wf = waveread(filename)  # ✅ Always pass the file path, not an open file

        if wf.getloops():
            self.loop = wf.getloops()[0][0]
            self.nframes = wf.getloops()[0][1] + 2
        else:
            self.loop = -1
            self.nframes = wf.getnframes()

        self.data = self.frames2array(wf.readframes(self.nframes), wf.getsampwidth(), wf.getnchannels())
        wf.close()


#########################################
# MIXER CLASSES
#########################################

class PlayingSound:
    def __init__(self, sound, note):
        self.sound = sound
        self.pos = 0
        self.fadeoutpos = 0
        self.isfadeout = False
        self.note = note

    def fadeout(self, i):
        self.isfadeout = True

    def stop(self):
        try:
            playingsounds.remove(self)
        except:
            pass

class Sound:
    def __init__(self, filename, midinote, velocity):
        wf = waveread(filename)  # ✅ Always pass the file path, not an open file
        self.fname = filename
        self.midinote = midinote
        self.velocity = velocity
        if wf.getloops():
            self.loop = wf.getloops()[0][0]
            self.nframes = wf.getloops()[0][1] + 2
        else:
            self.loop = -1
            self.nframes = wf.getnframes()
        self.data = self.frames2array(wf.readframes(self.nframes), wf.getsampwidth(), wf.getnchannels())
        wf.close()

    def play(self, note):
        snd = PlayingSound(self, note)
        playingsounds.append(snd)
        return snd

    def frames2array(self, data, sampwidth, numchan):
        if sampwidth == 2:
            npdata = numpy.frombuffer(data, dtype=numpy.int16)
        elif sampwidth == 3:
            npdata = samplerbox_audio.binary24_to_int16(data, len(data)//3)
        if numchan == 1:
            npdata = numpy.repeat(npdata, 2)
        return npdata

FADEOUTLENGTH = 30000
FADEOUT = numpy.linspace(1., 0., FADEOUTLENGTH)            # by default, float64
FADEOUT = numpy.power(FADEOUT, 6)
FADEOUT = numpy.append(FADEOUT, numpy.zeros(FADEOUTLENGTH, numpy.float32)).astype(numpy.float32)
SPEED = numpy.power(2, numpy.arange(0.0, 84.0)/12).astype(numpy.float32)

samples = {}
playingnotes = {}
sustainplayingnotes = []
sustain = False
playingsounds = []
globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
globaltranspose = 0
globaltranspose = 0

#########################################
# AUDIO AND MIDI CALLBACKS
#
#########################################

def AudioCallback(outdata, frame_count, time_info, status):
    global playingsounds
    rmlist = []
    playingsounds = playingsounds[-MAX_POLYPHONY:]
    b = samplerbox_audio.mixaudiobuffers(playingsounds, rmlist, frame_count, FADEOUT, FADEOUTLENGTH, SPEED)
    for e in rmlist:
        try:
            playingsounds.remove(e)
        except:
            pass
    b *= globalvolume
    outdata[:] = b.reshape(outdata.shape)

def MidiCallback(message, time_stamp):
    global playingnotes, sustain, sustainplayingnotes
    global preset
    
    if len(message) < 2:
        print("DEBUG: Ignoring malformed MIDI message:", message)
        return  # Ignore incomplete messages

    messagetype = message[0] >> 4
    messagechannel = (message[0] & 15) + 1
    note = message[1] if len(message) > 1 else None
    velocity = message[2] if len(message) > 2 else None
    
    if messagetype == 9 and velocity == 0:
        messagetype = 8  # Convert Note-On with Velocity 0 to Note-Off

    if messagetype == 9:  # Note On
        if velocity > 10:  # Ignore notes with very low velocity
            print(f"DEBUG: Playing Note {note} at Velocity {velocity}")
            try:
                playingnotes.setdefault(note, []).append(samples[note, velocity].play(note))
            except Exception as e:
                print(f"ERROR: Could not play sample for note {note}: {e}")
        else:
            print(f"DEBUG: Ignoring very low velocity note {note}, velocity {velocity}")
    elif messagetype == 8:  # Note Off
        if note in playingnotes:
            print(f"DEBUG: Releasing Note {note}")
            for n in playingnotes[note]:
                if sustain:
                    sustainplayingnotes.append(n)
                else:
                    n.fadeout(50)
            playingnotes[note] = []


    elif messagetype == 12:  # ✅ PROGRAM CHANGE
        print(f"DEBUG: Program Change {note}")  
        preset = note
        LoadSamples()

    elif messagetype == 11 and note == 64:  # ✅ SUSTAIN PEDAL
        if velocity < 64:
            print("DEBUG: Sustain Pedal OFF")
            for n in sustainplayingnotes:
                n.fadeout(50)
            sustainplayingnotes = []
            sustain = False
        else:
            print("DEBUG: Sustain Pedal ON")
            sustain = True


#########################################
# LOAD SAMPLES
#
#########################################

LoadingThread = None
LoadingInterrupt = False

def LoadSamples():
    global LoadingThread
    global LoadingInterrupt

    if LoadingThread:
        LoadingInterrupt = True
        LoadingThread.join()
        LoadingThread = None

    LoadingInterrupt = False
    LoadingThread = threading.Thread(target=ActuallyLoad)
    LoadingThread.daemon = True
    LoadingThread.start()

NOTES = ["c", "c#", "d", "d#", "e", "f", "f#", "g", "g#", "a", "a#", "b"]

def ActuallyLoad():
    global preset
    global samples
    global playingsounds
    global globalvolume, globaltranspose

    print(f"DEBUG: Loading preset: {preset}")
    playingsounds = []
    samples = {}
    globalvolume = 10 ** (-12.0/20)  # -12dB default global volume
    globaltranspose = 0
    samplesdir = "/home/hl/SamplerBox/samples/what"

    print(f"DEBUG: Checking sample directory: {samplesdir}")
    if not os.path.exists(samplesdir):
        print(f"ERROR: Sample directory {samplesdir} does NOT exist!")
        return
    print(f"DEBUG: Files in directory: {os.listdir(samplesdir)}")

    for filename in os.listdir(samplesdir):
        print(f"DEBUG: Processing file: {filename}")  # 👈 Add this line

        if filename.endswith(".wav"):
            try:
                midinote = int(filename.split('.')[0])  # Extracts note number
                samples[midinote, 127] = Sound(os.path.join(samplesdir, filename), midinote, 127)
                print(f"DEBUG: Loaded sample {filename} as MIDI note {midinote}")  # 👈 Add this line
            except ValueError:
                print(f"WARNING: Skipping file {filename} (Invalid filename format)")  # 👈 Add this line




    basename = "what"
    if basename:
        dirname = os.path.join(samplesdir, basename)
    if not basename:
        print('Preset empty: %s' % preset)
        display(f"L{preset}")
        return
    print('Preset loading: %s (%s)' % (preset, basename))
    display(f"L{preset}")
    definitionfname = os.path.join(dirname, "definition.txt")
    if os.path.isfile(definitionfname):
        with open(definitionfname, 'r') as definitionfile:
            for i, pattern in enumerate(definitionfile):
                try:
                    if r'%%volume' in pattern:        # %%paramaters are global parameters
                        globalvolume *= 10 ** (float(pattern.split('=')[1].strip()) / 20)
                        continue
                    if r'%%transpose' in pattern:
                        globaltranspose = int(pattern.split('=')[1].strip())
                        continue
                    defaultparams = {'midinote': '0', 'velocity': '127', 'notename': ''}
                    if len(pattern.split(',')) > 1:
                        defaultparams.update(dict([item.split('=') for item in pattern.split(',', 1)[1].replace(' ', '').replace('%', '').split(',')]))
                    pattern = pattern.split(',')[0]
                    pattern = re.escape(pattern.strip())  # note for Python 3.7+: "%" is no longer escaped with "\"
                    pattern = pattern.replace(r"%midinote", r"(?P<midinote>\d+)").replace(r"%velocity", r"(?P<velocity>\d+)")\
                                     .replace(r"%notename", r"(?P<notename>[A-Ga-g]#?[0-9])").replace(r"\*", r".*?").strip()    # .*? => non greedy
                    for fname in os.listdir(dirname):
                        print(f"DEBUG: Checking file {fname}")  # Debugging
                        if LoadingInterrupt:
                            return
                        m = re.match(pattern, fname)
                        if m:
                            info = m.groupdict()
                            midinote = int(info.get('midinote', defaultparams['midinote']))
                            velocity = int(info.get('velocity', defaultparams['velocity']))
                            notename = info.get('notename', defaultparams['notename'])
                            if notename:
                                midinote = NOTES.index(notename[:-1].lower()) + (int(notename[-1])+2) * 12
                            samples[midinote, velocity] = Sound(os.path.join(dirname, fname), midinote, velocity)
                except:
                    print("Error in definition file, skipping line %s." % (i+1))
    else:
        for midinote in range(0, 127):
            if LoadingInterrupt:
                return
            file = os.path.join(dirname, "%d.wav" % midinote)
            if os.path.isfile(file):
                samples[midinote, 127] = Sound(file, midinote, 127)
    initial_keys = set(samples.keys())
    for midinote in range(128):
        lastvelocity = None
        for velocity in range(128):
            if (midinote, velocity) not in initial_keys:
                samples[midinote, velocity] = lastvelocity
            else:
                if not lastvelocity:
                    for v in range(velocity):
                        samples[midinote, v] = samples[midinote, velocity]
                lastvelocity = samples[midinote, velocity]
        if not lastvelocity:
            for velocity in range(128):
                try:
                    samples[midinote, velocity] = samples[midinote-1, velocity]
                except:
                    pass
    if len(initial_keys) > 0:
        print('Preset loaded: ' + str(preset))
        if preset.isdigit():  # ✅ Check if preset is numeric before converting
            display("%04d" % int(preset))
        else:
            display(preset)  # ✅ Just display the preset name if it's not a number
    else:  # ✅ Correct indentation
        print('Preset empty: ' + str(preset))
        display(f"E{preset}")  # ✅ Corrected indentation

#########################################
# OPEN AUDIO DEVICE
#
#########################################

try:
    print(f"DEBUG: Attempting to open device {config.AUDIO_DEVICE_ID}")
        
    sd = sounddevice.OutputStream(
    device=int(config.AUDIO_DEVICE_ID),  # Make sure it's an integer
    blocksize=512,
    samplerate=44100,
    channels=2,
    dtype='int16',  # Ensure dtype is valid
    callback=AudioCallback
)






    sd.start()
    print(f"Opened audio device #{config.AUDIO_DEVICE_ID}")

except:
    print(f"Invalid audio device #{config.AUDIO_DEVICE_ID}")

    exit(1)

#########################################
# BUTTONS THREAD (RASPBERRY PI GPIO)
#
#########################################

#########################################
# 7-SEGMENT DISPLAY
#
#########################################

if USE_I2C_7SEGMENTDISPLAY:  # requires: 1) i2c-dev in /etc/modules and 2) dtparam=i2c_arm=on in /boot/config.txt
    import smbus
    bus = smbus.SMBus(1)     # using I2C
    def display(s):
        for k in '\x76\x79\x00' + s:     # position cursor at 0
            try:
                bus.write_byte(0x71, ord(k))
            except:
                try:
                    bus.write_byte(0x71, ord(k))
                except:
                    pass
            time.sleep(0.002)
    display('----')
    time.sleep(0.5)
else:
    def display(s):
        pass

#########################################
# MIDI IN via SERIAL PORT
#
#########################################

if USE_SERIALPORT_MIDI:
    import serial
    ser = serial.Serial(SERIALPORT_PORT, baudrate=SERIALPORT_BAUDRATE)
    def MidiSerialCallback():
        message = [0, 0, 0]
        while True:
            i = 0
            while i < 3:
                data = ord(ser.read(1))  # read a byte
                if data >> 7 != 0:
                    i = 0      # status byte!   this is the beginning of a midi message: http://www.midi.org/techspecs/midimessages.php
                message[i] = data
                i += 1
                if i == 2 and message[0] >> 4 == 12:  # program change: don't wait for a third byte: it has only 2 bytes
                    message[2] = 0
                    i = 3
            MidiCallback(message, None)
    MidiThread = threading.Thread(target=MidiSerialCallback)
    MidiThread.daemon = True
    MidiThread.start()

#########################################
# LOAD FIRST SOUNDBANK
#
#########################################

preset = "what"
LoadSamples()

#########################################
# SYSTEM LED
#
#########################################
if USE_SYSTEMLED:
    os.system("modprobe ledtrig_heartbeat")
    os.system("echo heartbeat >/sys/class/leds/led0/trigger")

#########################################
# MIDI DEVICES DETECTION
# MAIN LOOP
#########################################

def setup_midi():
    try:
        midi_in = [rtmidi.MidiIn(b'in')]
        print("MIDI system initialized successfully")
        return midi_in
    except Exception as e:
        print(f"Error initializing MIDI system: {str(e)}")
        print("Please check if:")
        print("1. Your MIDI device is properly connected")
        print("2. You have the necessary permissions")
        print("3. No other program is using the MIDI device")
        return None

def cleanup_midi(midi_devices):
    """Clean up MIDI resources properly"""
    if midi_devices:
        for device in midi_devices[1:]:  # Skip the first device as it's our port listener
            try:
                device.close_port()
            except:
                pass

# Initialize MIDI
try:
    midi_in = setup_midi()
    if not midi_in:
        print("Failed to initialize MIDI. Exiting...")
        sys.exit(1)

    previous = []
    while True:
        try:
            current_ports = midi_in[0].ports
            # Handle new ports
            for port in current_ports:
                if port not in previous and b'Midi Through' not in port:
                    try:
                        new_midi = rtmidi.MidiIn(b'in')
                        new_midi.callback = MidiCallback
                        new_midi.open_port(current_ports.index(port))
                        midi_in.append(new_midi)
                        print('Opened MIDI: ' + str(port))
                    except Exception as e:
                        print(f"Error opening MIDI port {port}: {str(e)}")
                        continue
            
            # Remove disconnected ports
            for i in range(len(midi_in)-1, 0, -1):  # Skip the first device
                try:
                    if not midi_in[i].is_port_open():
                        midi_in[i].close_port()
                        del midi_in[i]
                        print(f"Closed disconnected MIDI port")
                except:
                    pass
            
            previous = current_ports
            time.sleep(2)
        except KeyboardInterrupt:
            print("\nShutting down...")
            break
        except Exception as e:
            print(f"Error in main loop: {str(e)}")
            time.sleep(2)  # Wait before retrying
finally:
    cleanup_midi(midi_in)
    if 'sd' in globals():
        sd.stop()
    print("Cleanup complete")
