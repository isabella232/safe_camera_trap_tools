import os
import re
from itertools import groupby

# Get a structure holding the directories
gen = os.walk('.')

data = {}

for path, dirs, files in gen:
    
    data[path] = [{'path': path, 'n': len(files)}]

# There are groups of folders, identified by terminal numbers, which
# contain images from the same deployment. They end with either a 
# bracketed number [(n)] or just a number, so look for sets of folders
# that differ only in this ending. 

# Where an image folder ends with a terminal number, return a tuple of
# base and base + number. The regexes here are a little complex:
# - 'base (n)' or 'base(n)' isn't too bad 
#    --> " ?\(\d+\)$"
# - 'basen or base n is more difficult because we have to avoid locations like D1-2-24 
#    --> "(?<![-\d]) ?\d+$"
# Note that n can rarely be > 9

regex = re.compile(' ?\(\d+\)$|(?<![-\d]) ?\d+$')
has_tn = [(ky[:regex.search(ky).start()], ky) for ky in data.keys() if regex.search(ky) is not None]

# Group those tuples and group the folders under the common root
has_tn.sort(key=lambda x: x[0])
for ky, gp in groupby(has_tn, key=lambda x: x[0]):
    data[ky.strip()] = [data.pop(g[1])[0] for g in list(gp)]

# Now pop out any entries that don't contain files - parent or empty folders 
empty = [ky for ky, dt in data.items() if sum([d['n'] for d in dt]) == 0]
for ky in empty:
    data.pop(ky)

#  Now split into calibration and non calibration
regex = re.compile('calib', re.IGNORECASE)
calibration = {ky: dt for ky, dt in data.items() if regex.search(ky) is not None}
images = {ky: dt for ky, dt in data.items() if regex.search(ky) is None}

# The deployments dictionary is keyed by deployment base id and will 
# hold subdictionaries containing:
#   'images': a list of image folders
#   'calib': a list of calibration folders

deployments = {}

# 1) Deal with the common pattern:
#   ../path/path/location/
#   ../path/path/location/location CALIB

images_basename = [os.path.basename(dr) for dr in images.keys()]
calib_keys = list(calibration.keys())
image_keys = list(images.keys())

for path, bsnm in zip(image_keys, images_basename):
    
    # Find calibration folders that match the whole path with the location 
    # CALIB suffix and add those to the deployments 
    calib_path = path + '/' + bsnm + ' CALIB'
    try:
        idx = calib_keys.index(calib_path)
        deployments[path] = {'images': images.pop(path),
                             'calib': calibration.pop(calib_keys[idx])}
    except ValueError:
        pass
        

# 2) Second common pattern
#    ./Ollie's Core PhD Images/Virgin Jungle Reserve/161212 CALIB/VJRN-2-2 CALIB
#    ./Ollie's Core PhD Images/Virgin Jungle Reserve/VJRN-2-2

calib_keys = list(calibration.keys())

for ky in calib_keys:
    
    path_parts = os.path.split(ky)
    location = re.sub(' CALIB$', '', path_parts[1])
    image_folder = os.path.join(os.path.split(path_parts[0])[0], location)
    
    if image_folder in images:
        deployments[image_folder] = {'images': images.pop(image_folder),
                                     'calib': calibration.pop(ky)}


                                     