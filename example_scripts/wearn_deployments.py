import os
import re
from itertools import groupby
import safe_camera_trap_tools as sctt

# Get a list holding the directories with any files in them
gen = os.walk('Wearn_camera_traps')

data = []
for path, dirs, files in gen:
    if len(files):
        data.append(path)

# The folder structure contains some groups of folders where a single deployment
# is split across multiple directories, for both calibration and standard
# images. These directories are identified by having an ending number. In order
# to handle these more easily, we repackage data into a dictionary of lists of
# folders keyed by the common path with the number removed. 

# Using regex to do this, there are some common features:
# - the terminal number _can_ be > 9 so need to use \d+
# - some CALIB folders are within folders with terminal numbers, so the lookup
#   needs to find the end of a string or a path separator, so ends with a positive 
#   lookahead (?=/|$).

# Pattern 1: 'xxx (n)' or 'xxx(n)'
#    --> " ?\(\d+\)(?=/|$)"

# Check what this catches:

regex = re.compile(" ?\(\d+\)(?=/|$)")
captures = [regex.search(x) for x in data]
set([x[0] for x in captures if x is not None])

# It also catches two deeper folders with bracketed numbers: removing and grouping
# by these names has no effect, so we can leave as is
# - /Benta (Tagged)/Benta I (27)/
# - /Benta II (56)/

# Pattern 2: 'base n'
regex = re.compile(" \d+(?=/|$)")
captures = [regex.search(x) for x in data]
set([x[0] for x in captures if x is not None])

# This also catches some other deeper folders but again neither matter for the
# purposes of grouping folders.
# - OP1-3 From Jack/XXX Deployment XXX Check XXX 2014/
# - Arboreal Camera trap photos/Camera 102

# Pattern 3: CALIBn
regex = re.compile("(?<=CALIB)\d(?=/|$)")
captures = [regex.search(x) for x in data]
set([x[0] for x in captures if x is not None])

# Pattern 4: directory consisting of just a number (with in two cases 
# ' - changed direction' as a suffix).
regex = re.compile("/\d( - changed direction)?$")
captures = [regex.search(x) for x in data]
set([x[0] for x in captures if x is not None])

# SO now match all three patterns and return a string with the matches stripped
# out

regex = re.compile(' ?\(\d+\)(?=/|$)| \d+(?=/|$)|(?<=CALIB)\d(?=/|$)|/\d( - changed direction)?$')
tn_removed = [regex.sub('', x) for x in data]

# Make tuples of base name and full name, sort and group
data = list(zip(tn_removed, data))
data.sort(key=lambda x: x[0])

data_grouped = {}
for ky, gp in groupby(data, key=lambda x: x[0]):
    data_grouped[ky] = [g[1] for g in list(gp)]

# Now build up a list of deployments containing dictionaries with:
#   'loc': location
#   'images': a list of image folders
#   'calib': a list of calibration folders

# Transfer lists of folders from data_grouped into deployments using different recipes

deployments = []

# 1) Amy Fitzmaurice images
# - just create the image folders - no calibration images

data_keys = list(data_grouped.keys())

for this_dir in data_keys:
    if this_dir.find("Amy's MSc Images") > 0:
        location = os.path.basename(this_dir)
        deployments.append({'loc': location, 'images': data_grouped.pop(this_dir), 'calib':[]})

# 2) Oil palm images "From Jack". There are four folders, clearly labelled as two visits to
#    two deployments. There is good overlap between the locations within deployments (not perfect 
#    so presumably some cameras had no detections in one or other of the deployments). Amalgamate
#    these into deployments

jack_dep = {'jack1': 'From Jack/1st', 'jack2':'From Jack/2nd'}

for ky, jdep in jack_dep.items():
    
    # find the folders within this deployment
    jack = [x for x in data_keys if x.find(jdep) > 0]
    
    # Strip calib off and group by the  final folder name
    jack = [(os.path.basename(x).replace(' CALIB',''), x) for x in jack]
    
    jack.sort(key=lambda x: x[0])
    jack = groupby(jack, key=lambda x: x[0])
    
    for loc, gp in jack:
        
        # Get the folder keys from the grouper and hence the folder lists
        fkeys = [g[1] for g in list(gp)]
        imcb = [data_grouped.pop(ky) for ky in fkeys]
        # unwrap grouped lists into a single list
        imcb = [item for sublist in imcb for item in sublist]
        # separate calib
        cb = [x for x in imcb if x.find('CALIB') > 0]
        im = list(set(imcb) - set(cb))
        
        deployments.append({'loc': loc, 'images': im, 'calib': cb})

# 3) Deal with the common pattern:
#   ../path/path/location/
#   ../path/path/location/location CALIB

# reresh the list  of remaining keys
data_keys = list(data_grouped.keys())

for ky in data_keys:
    
    loc = os.path.basename(ky)
    calib_ky = os.path.join(ky, loc + ' CALIB')
    if calib_ky in data_keys:
        im = data_grouped.pop(ky)
        cb = data_grouped.pop(calib_ky)
        deployments.append({'loc': loc, 'images': im, 'calib': cb})


# 4) Second common pattern
#    ./Ollie's Core PhD Images/Virgin Jungle Reserve/161212 CALIB/VJRN-2-2 CALIB
#    ./Ollie's Core PhD Images/Virgin Jungle Reserve/VJRN-2-2

# reresh the list  of remaining keys
data_keys = list(data_grouped.keys())
regex = re.compile('CALIB/[-A-Z0-9]+ ')
cb_keys = [ky for ky in data_keys if regex.search(ky) is not None]
cb_loc = [os.path.basename(ky).replace(' CALIB', '') for ky in cb_keys]
cb_base = [os.path.dirname(os.path.dirname(ky)) for ky in cb_keys]
image_keys = [os.path.join(dr, lc) for dr, lc in zip(cb_base, cb_loc)]

for im, cb in zip(image_keys, cb_keys):
    if im in data_grouped:
        deployments.append({'loc': loc, 
                            'images': data_grouped.pop(im), 
                            'calib': data_grouped.pop(cb)})

# 5) There are still some remaning CALIB folders which are resolved case by case

rt = "Wearn_camera_traps/Ollie's Core PhD Images/SAFE Experimental Area/"

# Typo in calib
im = "Benta December E (Not Yet Analysed)/E1-2-22"
cb = "Benta December E (Not Yet Analysed)/E1-2-22/E1-2-20 CALIB"

deployments.append({'loc': 'E1-2-22', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

# Notes in folder name - I have _not_ shifted the dates
im = "Benta December E (Not Yet Analysed)/E10-1-12"
cb = "Benta December E (Not Yet Analysed)/E10-1-12/E10-1-12 CALIB (need shift date plus 12)"

deployments.append({'loc': 'E10-1-12', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

# Missing space
im = "Benta (Not Yet Analysed)/Benta II/D10-1-21"
cb = "Benta (Not Yet Analysed)/Benta II/D10-1-21/D10-1-21CALIB"

deployments.append({'loc': 'D10-1-21', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

# This is guesswork but two CALIB folders have _nearly_ matching locations
# folders, the serial numbers of the cameras match and the image times are
# within a day.

im = "Benta E, B & F (April 2013)/F100-1-17"
cb = "Benta E, B & F (April 2013)/160413 CALIB/F100-2-17 CALIB"

deployments.append({'loc': 'F100-1-17', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})


im = "Benta E, B & F (April 2013)/F100-1-25"
cb = "Benta E, B & F (April 2013)/160413 CALIB/F100-2-25 CALIB"

deployments.append({'loc': 'F100-1-25', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

im = "Benta E, B & F (April 2013)-images with malfunction/E1-2-6"
cb = "Benta E, B & F (April 2013)/080413 CALIB/E1-2-6 CALIB"

deployments.append({'loc': 'E1-2-6', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})


# Four CALIB folders with no obvious image folders - nothing tripped the camera? malfunction?
cb = "Benta E, B & F (April 2013)/130413 CALIB/B1-1-8 CALIB"
deployments.append({'loc': 'B1-1-8', 
                    'images': [], 
                    'calib': data_grouped.pop(rt + cb)})


cb = "Benta E, B & F (April 2013)/160413 CALIB/F10-1-41 1st setup - camera malfunctioned"
deployments.append({'loc': 'F10-1-41', 
                    'images': [], 
                    'calib': data_grouped.pop(rt + cb)})

rt = "Wearn_camera_traps/Ollie's Core PhD Images/"

cb = "Virgin Jungle Reserve/171212 CALIB/VJRS-1-22 CALIB"
deployments.append({'loc': 'VJRS-1-22', 
                    'images': [], 
                    'calib': data_grouped.pop(rt + cb)})

cb = "Maliau Basin/3rd Round (OG3)/OG3-W-39 CALIB"
deployments.append({'loc': 'OG3-W-39', 
                    'images': [], 
                    'calib': data_grouped.pop(rt + cb)})

# Two folders ending (setup) == CALIB ?
rt = "Wearn_camera_traps/Ollie's Core PhD Images/Oil Palm/"

im = "1st Check/OP2-W-42"
cb = "1st Check/OP2-W-42 (setup)"

deployments.append({'loc': 'F100-1-25', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

im = "1st Check/OP2-W-47"
cb = "1st Check/OP2-W-47 (setup)"

deployments.append({'loc': 'F100-1-25', 
                    'images': data_grouped.pop(rt + im), 
                    'calib': data_grouped.pop(rt + cb)})

# 6) What is left are image folders with no obvious calibration images. Strip
# out the ones with an obvious location code (including one with a (b) suffix)

data_keys = list(data_grouped.keys())
regex = re.compile('\w+-\w{1,4}-\w+$')
loc_keys = [ky for ky in data_keys if regex.search(ky) is not None]
locs = [regex.search(ky)[0] for ky in loc_keys]

for lc, ky in zip(locs, loc_keys):
    
    deployments.append({'loc': lc, 'images': data_grouped.pop(ky), 'calib': []})


# 7) Remaining ones by hand:

rt = "Wearn_camera_traps/Ollie's Core PhD Images/Maliau Basin/1st Round/"

deployments.append({'loc': "OG2-N-38", 
                    'images': data_grouped.pop(rt + "Fully Random/OG2-N-38(B)"), 
                    'calib': []})

deployments.append({'loc': "Knowledge_Trail", 
                    'images': data_grouped.pop(rt + "Non-random On-trail/KnowTr1"), 
                    'calib': []})

deployments.append({'loc': "Knowledge_Trail", 
                    'images': data_grouped.pop(rt + "Non-random On-trail/KnowTr2"), 
                    'calib': []})

deployments.append({'loc': "Belian_Trail", 
                    'images': data_grouped.pop(rt + "Non-random On-trail/TrailBelianPlots1"), 
                    'calib': []})

deployments.append({'loc': "Seraya_Trail", 
                    'images': data_grouped.pop(rt + "Non-random On-trail/TrailSerayaPlots1"), 
                    'calib': []})

deployments.append({'loc': "Seraya_Trail", 
                    'images': data_grouped.pop(rt + "Non-random On-trail/TrailSerayaPlots2"), 
                    'calib': []})

rt2 = rt + "Non-random Off-trail/Inside Plots/"

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-E-Nonrandom-5"), 
                    'calib': []})

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-W-Nonrandom-3"), 
                    'calib': []})

rt2 = rt + "Non-random Off-trail/Outside Plots/"

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-E-Nonrandom-2"), 
                    'calib': []})

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-N-Nonrandom-6"), 
                    'calib': []})

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-N-Nonrandom-7"), 
                    'calib': []})

deployments.append({'loc': "OG2-E", 
                    'images': data_grouped.pop(rt2 + "OG2-E-W-Nonrandom-4"), 
                    'calib': []})

deployments.append({'loc': "OG2", 
                    'images': data_grouped.pop(rt2 + "OG2-Nonrandom-8"), 
                    'calib': []})

deployments.append({'loc': "OG2", 
                    'images': data_grouped.pop(rt2 + "OG2-Nonrandom-9"), 
                    'calib': []})

# Final arboreal images

im = (data_grouped.pop('Wearn_camera_traps/Arboreal Camera trap photos') +
      data_grouped.pop('Wearn_camera_traps/Arboreal Camera trap photos/Camera'))

deployments.append({'loc': "Arboreal", 
                    'images': im, 
                    'calib': []})

#
# PROCESS THE SET OF DEPLOYMENTS
#

for dep in deployments:
    
    # process the deployment
    gathered = sctt.gather_deployment_files(dep['images'], dep['loc'], dep['calib'])
    
    # Create the output directory
    year = gathered['date'].strftime('%Y')
    outdir = os.path.join('deployments', year)
    if not os.path.exists(outdir):
        os.mkdir(outdir)
    
    # Now copy the files across
    deployment_dir = sctt.create_deployment(gathered, output_root=outdir)
    
    # These files have already been annotated, so extract the deployment data
    # into the deployment folder
    sctt.extract_deployment_data(deployment_dir)
