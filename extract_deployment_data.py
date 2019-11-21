import os
import sys
import argparse
import datetime
import csv
from itertools import groupby
from collections import OrderedDict
import re
import exiftool

"""
This script takes a single deployment folder and extracts EXIF data and other 
statistics into a common format. It duplicates the information extracted by an 
earlier tool written in R that extracted EXIF data from an exiftool dump to csv
for a folder.  
"""


def extract_deployment_data(deployment, outfile=None):

    """
    This function extracts the key EXIF data from a deployment folder, creating
    a tab-delimited output file holding image level data with a short deployment
    header.

    Args:
        deployment: A path to a deployment directory
        outfile: A path to a file to hold the extracted data as tab delimited text,
            defaulting to saving the data as 'exif_data.dat' within the deployment 
            directory
    """

    # LOAD THE EXIF DATA FROM IMAGE AND CALIB DIRECTORIES
    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # Check the deployment folder exists
    if not os.path.exists(deployment) and os.path.isdir(deployment):
        raise IOError('Deployment path does not exist or is not a directory.')

    if outfile is None:
        outfile = os.path.join(deployment, 'exif_data.csv')

    print(f'Extracting EXIF data from {deployment}', file=sys.stdout, flush=True)

    # Find images, extract EXIF data and flag as non-calibration images
    images = os.listdir(deployment)
    images = [im for im in images if im.lower().endswith('.jpg')]
    images_exif = et.get_metadata_batch([os.path.join(deployment, im) for im in images])
    _ =[entry.update({'Calib': 0}) for entry in images_exif]

    # check for any calibration images
    calib_dir = os.path.join(deployment, 'CALIB')
    if os.path.exists(calib_dir):
        # get exif data from calibration images
        calib = os.listdir(calib_dir)
        calib = [im for im in calib if im.lower().endswith('.jpg')]
        calib_exif = et.get_metadata_batch([os.path.join(calib_dir, im) for im in calib])
        _ =[entry.update({'Calib': 1}) for entry in calib_exif]
    else:
        calib_exif = []
    
    # Combine and continue
    exif = images_exif + calib_exif
    n_exif = len(exif)
    
    # Reduce to tags used in rest of the script, filling in blanks and simplifying tag names
    keep_tags = ['EXIF:Make', 'EXIF:Model', 'MakerNotes:SerialNumber', 'Calib',
                 'MakerNotes:FirmwareDate', 'File:ImageHeight', 'File:ImageWidth',
                 "File:FileName", "EXIF:CreateDate", "EXIF:ExposureTime", "EXIF:ISO",
                 "EXIF:Flash", "MakerNotes:InfraredIlluminator", "MakerNotes:MotionSensitivity",
                 "MakerNotes:AmbientTemperature", "EXIF:SceneCaptureType",
                 "MakerNotes:Sequence", "MakerNotes:TriggerMode", 'IPTC:Keywords']
    
    # convert keep_tags to 2-tuples of current name and simplified name
    exif_group = re.compile('[A-z]+:')
    keep_tags = [(vl, exif_group.sub('', vl)) for vl in keep_tags]
    
    for idx, entry in enumerate(exif):
        exif[idx] = {short_key: entry.get(long_key, None) for long_key, short_key in keep_tags}
    
    # EXTRACT KEYWORD TAGGING - The image tagging process populates the IPTC:Keywords tag
    # with a list of tags that need to be expanded out into their own fields in the output.
    
    # 1) First, unpack keywords into a subdictionary if they are present
    #    The keywords are strings with the format 'tag_number: value', where tag 
    #    number can be repeated. The process below combines duplicate tag numbers 
    #    and strips whitespace padding.
    #    
    #    For example:
    #    ['15: E100-2-23', '16: Person', '16: Setup', '24: Phil']
    #    goes to
    #    {'15': 'E100-2-23', '16': 'Person, Setup', '24': 'Phil'}
    
    
    for entry in exif:
        if entry['Keywords'] is None:
            entry['Keywords'] = {}
        else:
            # Split the strings on colons
            kw_list = [kw.split(':') for kw in entry['Keywords']]
            # Sort and group on tag number
            kw_list.sort(key=lambda x: x[0])
            kw_groups = groupby(kw_list, key=lambda x: x[0])
            # Turn that into a dictionary 
            kw_dict = {}
            for key, vals in kw_groups:
                kw_dict['Tag_' + key] = ', '.join(vl[1].strip() for vl in vals)
            # Replace the original list with the new dictionary
            entry['Keywords'] = kw_dict
    
    # 2) Find the common set of tags, in order to populate the file dictionaries
    #    with complete entries, including blanks for missing tags
    keyword_tags = [list(d['Keywords'].keys()) for d in exif]
    keyword_tags = set([tg for tag_list in keyword_tags for tg in tag_list])
    
    # 3) Move the keyword tags from inside entry['Keywords'] to entry, 
    #    populating the full set of tags in the deployment along the way 
    #    and then delete entry['Keywords']
    for entry in exif:
        keywords = entry['Keywords']
        keywords = {tag: keywords.get(tag, None) for tag in keyword_tags}
        entry.update(keywords)
        del entry['Keywords']
    
    # REPORTING AND VALIDATION
    
    # Get dictionary of fields - processing so far using dict.get(vl, None)
    # should ensure that all keys are present for all files.
    exif_fields = {k: [dic[k] for dic in exif] for k in exif[0]}
    
    # DEPLOYMENT level data
    print('Checking for consistent deployment data', file=sys.stdout, flush=True)
    dep_data = OrderedDict()
    
    # A) Check for consistent camera data
    camera_fields = ['Make', 'Model', 'SerialNumber', 'FirmwareDate',
                     'ImageHeight', 'ImageWidth']
    
    for fld in camera_fields:
        vals = set(exif_fields[fld])
        if len(vals) > 1:
            vals = ', '.join(vals)
            print(f"  ! {fld} is not consistent: {vals}", file=sys.stderr, flush=True)
        else:
            vals = list(vals)[0]
        
        dep_data[fld] = vals
    
    # B) Check for date information 
    #    EXIF should have a consistent datetime format: "YYYY:mm:dd HH:MM:SS"
    image_dates = [datetime.datetime.strptime(vl, '%Y:%m:%d %H:%M:%S') 
                   for vl in exif_fields['CreateDate'] if vl is not None]
    
    if not image_dates:
        print('  ! No CreateDate tags found', file=sys.stderr, flush=True )
    else:
        # get the date range
        start_dt = min(image_dates)
        end_dt = max(image_dates)
        n_days = (end_dt - start_dt).days + 1
        dep_data['start'] = str(start_dt)
        dep_data['end'] = str(end_dt)
        dep_data['n_days'] = n_days
        
        # report on missing dates
        if len(image_dates) < n_exif:
            print(f'  ! CreateDate tags not complete: {len(image_dates)}/{n_exif}', 
                  file=sys.stderr, flush=True)
            dep_data['n_missing_dates'] = n_exif - len(image_dates)
    
    # C) Check location data (only keyword tag that should be constant)
    if 'Tag_15' not in exif_fields:
        print('  ! No location tags (15) found', file=sys.stderr, flush=True)
    else:
        # Get the unique tagged locations
        locations = set(exif_fields['Tag_15'])
        
        # Are they consistent with the deployment folder
        match_folder = [os.path.basename(deployment).startswith(l) for l in locations]
        
        if len(locations) > 1:
            locations = ', '.join(locations)
            print(f'  ! Location tags (15) not internally consistent: {locations}',
                  file=sys.stderr, flush=True)
        else:
            locations = list(locations)[0]
        
        if not any(match_folder):
            print('  ! Location tags (15) do not match deployment folder.',
                  file=sys.stderr, flush=True)
        
        dep_data['location'] = locations
    
    # Add the number of images
    dep_data['n_images'] = len(images_exif)
    dep_data['n_calib'] = len(calib_exif)
    
    # print to screen to report
    print('Deployment data:', file=sys.stdout, flush=True)
    dep_lines = [f'{ky}: {vl}' for ky, vl in dep_data.items()]
    print(*['    ' + d +'\n' for d in dep_lines], file=sys.stdout, flush=True)
    
    # IMAGE level data
    # report on keyword tag completeness:
    if not keyword_tags:
        print(' ! No Image keyword tags found', file=sys.stderr, flush=True)
    else:
        print('Image tag counts:', file=sys.stdout, flush=True)
        for kywd in keyword_tags:
            n_found = sum([vl is not None for vl in exif_fields[kywd]])
            print(f'    {kywd:10}{n_found:6}', file=sys.stdout, flush=True)
    
    # WRITE data to files
    with open(outfile, 'w') as outf:
        # Header containing constant deployment data
        outf.writelines(ln + '\n' for ln in dep_lines)
        outf.write('---\n')
    
    with open(outfile, 'a') as outf:
        # Tab delimited table of image data
        writer = csv.writer(outf, delimiter='\t', lineterminator='\n')
        data = zip(*exif_fields.values())
        writer.writerow(exif_fields.keys())
        writer.writerows(data)
    
    # tidy up
    sys.stdout.write('Data written to {}\n'.format(outfile))
    et.terminate()


def main():

    """
    This program consolidates a set of camera trap image folders from a single
    deployment into a single folder, renaming the images to a standardised format.

    It does _not_ alter the original folders: all of the images are copied into
    a new folder. It also checks that all of the new images are getting unique names
    before starting to copy files.
    """

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('deployment',
                        help='A path to a deployment directory')
    parser.add_argument('-o', '--outfile', default=None,
                        help='A path to a file to hold the extracted data')

    args = parser.parse_args()

    extract_deployment_data(deployment=args.deployment, outfile=args.outfile)


if __name__ == "__main__":
    main()
