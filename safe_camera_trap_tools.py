import os
import sys
import argparse
import datetime
import csv
import shutil
from itertools import groupby
import textwrap
import re
import exiftool
import progressbar


# TODO - Figure out how to share the docstrings between the functions and their CLI wrappers

def _process_folder(image_dir, location, et):

    """
    This private function processes a single folder of images. It reads the EXIF data for each JPEG
    file in the folder and uses this and the provided location name to create the new filename. It
    also tracks and returns the earliest creation datetime, used to create the deployment folder
    name.
    
    Args:
        image_dir: The directory to process
        location: The name of the location to be used as the deployment name
        et: An exiftool instance
    
    Returns:
        A list of two-tuples [(file_name, new_name)] and the earliest creation date found as a
        datetime.datetime object.
    """

    print(f'Processing directory: {image_dir}', file=sys.stdout, flush=True)
    
    # Load list of files, ignoring nested directories and then separate JPEGS
    files =  next(os.walk(image_dir))[2]
    jpeg_files = [fl for fl in files if fl.lower().endswith('jpg')]
    other_files = set(files) - set(jpeg_files) 
    
    # report on what is found
    print(f' - Found {len(jpeg_files)} JPEG files', file=sys.stdout, flush=True)

    if other_files:
        print(f' - *!* Found {len(other_files)} other files: {", ".join(other_files)}',
              file=sys.stdout, flush=True)
    
    # Handle folders with no images:
    if len(jpeg_files):
        print(' - Scanning EXIF data', file=sys.stdout, flush=True)

        # get full paths
        paths = [os.path.join(image_dir, fl) for fl in jpeg_files]

        # get creation date and sequence tag from EXIF
        tags = ['EXIF:CreateDate', u'MakerNotes:Sequence']
        tag_data = et.get_tags_batch(tags, paths)

        # check tags found and report first five file names
        report_n = 5
        
        # Look for Sequence tag, falling back to file names if sequence is missing
        tg = u'MakerNotes:Sequence'
        sequence = [td[tg] if tg in td else None for td in tag_data]
        
        if None in sequence:
            # Look for sequence information embedded in the file names
            regex = re.compile('\d+(?= of \d+.jpg)')
            fseq = [regex.search(f) for f in jpeg_files]
            fseq = [f[0] if f is not None else None for f in fseq]
            
            # merge with exif sequence data, preferring exif
            sequence = [exval if exval is not None else fval for exval, fval in zip(sequence, fseq)]
        
        # Look to see if any sequences _still_ missing
        if None in sequence:
            tag_missing = [fl for fl, sq in zip(files, sequence) if sq is None]
            if len(tag_missing):
                n_missing = len(tag_missing)
                report_missing = ','.join(tag_missing[0:report_n])
                if report_n < n_missing:
                    report_missing += ", ..."
                raise RuntimeError(f'{n_missing} files missing sequence number: {report_missing}')

        # Look for create date tag
        tg = u'EXIF:CreateDate'
        create_date = [td[tg] if tg in td else None for td in tag_data]
        if None in create_date:
            tag_missing = [fl for fl, cd in zip(files, create_date) if cd is None]
            if len(tag_missing):
                n_missing = len(tag_missing)
                
                report_missing = ','.join(tag_missing[0:report_n])
                if report_n < n_missing:
                    report_missing += ", ..."
                raise RuntimeError(f'{n_missing} files missing creation date tag: {report_missing}')
        
    
        # Generate new file names:
        # a) Get file datetimes
        create_date = [datetime.datetime.strptime(td['EXIF:CreateDate'], '%Y:%m:%d %H:%M:%S')
                       for td in tag_data]
        # b) in burst mode, time to seconds is not unique, so add sequence number
        # c) put those together
        new_name = [location + "_" + dt.strftime("%Y%m%d_%H%M%S") + seq + ".jpg"
                    for dt, seq in zip(create_date, sequence)]
    
        # Get earliest date
        min_date = min(create_date)
    
        # Return a list of tuples [(src, dest), ...] and the earliest creation date
        return(list(zip(paths, new_name)), min_date)
    else:
        return([], datetime.datetime(1,1,1))



def _convert_keywords(keywords):
    
    """ Unpacks a list of keywords into a dictionary. The keywords are strings with the format
    'tag_number: value', where tag number can be repeated. The process below combines duplicate tag
    numbers and strips whitespace padding.
    
    For example:
        ['15: E100-2-23', '16: Person', '16: Setup', '24: Phil']
    goes to
        {'Tag_15': 'E100-2-23', 'Tag_16': 'Person, Setup', 'Tag_24': 'Phil'}
    """
    
    if keywords is None:
        return {}
    
    if isinstance(keywords, str):
        keywords = [keywords]
    
    # Split the strings on colons
    kw_list = [kw.split(':') for kw in keywords]
    
    # Sort and group on tag number
    kw_list.sort(key=lambda x: x[0])
    kw_groups = groupby(kw_list, key=lambda x: x[0])
    
    # Turn that into a dictionary 
    kw_dict = {}
    for key, vals in kw_groups:
        kw_dict['Tag_' + key] = ', '.join(vl[1].strip() for vl in vals)
    
    return kw_dict


def validate_folder(image_dir):
    
    """Extracts key EXIF data from a folder of images and performs some validation, returning a set
    of folder level data and image-specific EXIF information.
    
    Args:
        image_dir: A path to a directory of images
    
    Returns:
        A dictionary containing:
        - folder_data: A dictionary of what should be consistent folder level data, such as the
          camera details, location and start and stop dates.
        - image_data: A dictionary of fields of EXIF data for each image in the folder. Keyword
          tags are separated out into to their own fields. This includes the image name within
          image_dir.
        - other_files: A list of non-image files in image_dir
        - issues: A list of tags flagging any common issues with the directory.
        - image_dir: The provided directory name
        - keyword_tags: A list of keyword fields extracted from the IPTC:Keywords data.
    """
    
    # ----------------------------------------------------------------------------------------
    # Step 1: Identify the files and load exif data 
    # ----------------------------------------------------------------------------------------
    
    # collect issues in a list
    issues = []
    
    # get the files and subset to images
    files =  next(os.walk(image_dir))[2]
    images = [fl for fl in files if fl.lower().endswith('jpg')]
    other_files = set(files) - set(images) 
    
    if other_files:
        issues.append('extra_files')
    
    # Bail if there are no image files
    if not images:
        issues.append('no_images')
        return {'issues': issues}
    
    # Otherwise get the key tags 
    target_tags = ["EXIF:Make", "EXIF:Model", "MakerNotes:SerialNumber", "Calib",
                   "MakerNotes:FirmwareDate", "File:ImageHeight", "File:ImageWidth",
                   "File:FileName", "EXIF:CreateDate", "EXIF:ExposureTime", "EXIF:ISO",
                   "EXIF:Flash", "MakerNotes:InfraredIlluminator", "MakerNotes:MotionSensitivity",
                   "MakerNotes:AmbientTemperature", "EXIF:SceneCaptureType",
                   "MakerNotes:Sequence", "MakerNotes:TriggerMode", "IPTC:Keywords"]
    
    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()
    exif = et.get_tags_batch(target_tags, [os.path.join(image_dir, im) for im in images])
    et.terminate()
    
    # Simplify tag names: convert target_tags to 2-tuples of current name and
    # simplified name and then sub them in
    exif_group = re.compile('[A-z]+:')
    target_tags = [(vl, exif_group.sub('', vl)) for vl in target_tags]
    
    for idx, entry in enumerate(exif):
        exif[idx] = {short_key: entry.get(long_key, None) for long_key, short_key in target_tags}
    
    # Convert list of dictionaries to dictionary of list
    # - use of dict.get(vl, None) above ensures all keys in target_tags are populated for all files
    n_exif = len(exif)
    exif_fields = {k: [dic[k] for dic in exif] for k in exif[0]}
    
    # ----------------------------------------------------------------------------------------
    # Step 2: Extract keyword tags
    # The image tagging process populates the IPTC:Keywords tag with a list of tags that 
    # need to be expanded out into their own fields in the output.
    # ----------------------------------------------------------------------------------------
    
    if 'Keywords' not in exif_fields or not list(filter(None.__ne__, exif_fields['Keywords'])):
        issues.append('no_keywords')
    else:
        if None in exif_fields['Keywords']:
            issues.append('missing_keywords')
        
        exif_fields['Keywords'] = [_convert_keywords(kw) for kw in exif_fields['Keywords']]
    
    # Find the common set of tags, in order to populate the file dictionaries with complete
    # entries, inserting None for missing tags
    keyword_tags = [list(d.keys()) for d in exif_fields['Keywords']]
    keyword_tags = set([tg for tag_list in keyword_tags for tg in tag_list])
    
    for kw_tag in keyword_tags:
        exif_fields[kw_tag] = [tags.get(kw_tag, None) for tags in exif_fields['Keywords']]
    
    del exif_fields['Keywords']
    
    # ----------------------------------------------------------------------------------------
    # Step 3: Folder level data checks - things that should be consistent within a folder
    # ----------------------------------------------------------------------------------------
    
    folder_data = {}
    
    # a) Check for consistent camera data
    camera_fields = ['Make', 'Model', 'SerialNumber', 'FirmwareDate', 'ImageHeight', 'ImageWidth']
    
    for fld in camera_fields:
        vals = list(set(exif_fields[fld]))
        folder_data[fld] = vals
    
    if any([len(x) > 1 for x in folder_data.values()]):
        issues.append("camera_data_inconsistent")
    
    if None in [item for sublist in folder_data.values() for item in sublist]:
        issues.append("camera_data_incomplete")
    
    # b) Check location data (the only keyword tag that should be constant within a folder)
    if 'Tag_15' not in exif_fields:
        issues.append('no_locations')
    else:
        # Get the unique tagged locations
        tag_loc = list(set(exif_fields['Tag_15']))
        
        # Check for missing location tags (Tag_15: None) and remove. Note that Tag_15 won't
        # be present at all if there are _no_ 15 keyword entries, so there should be something
        # other than None here.
        if None in tag_loc:
            issues.append('missing_locations')
            tag_loc = list(filter(None.__ne__, tag_loc))
                
        if len(tag_loc) > 1:
            issues.append(f'locations_inconsistent')
        
        folder_data['location'] = tag_loc
    
    # ----------------------------------------------------------------------------------------
    # Step 4: Image level data checks - things that are needed for each image
    # ----------------------------------------------------------------------------------------
    
    # a) Check for date information 
    #    EXIF should have a consistent datetime format: "YYYY:mm:dd HH:MM:SS"
    if 'CreateDate' not in exif_fields or not list(filter(None.__ne__, exif_fields['CreateDate'])):
        issues.append('no_dates')
    else:
        image_dates = [vl if vl is None else datetime.datetime.strptime(vl, '%Y:%m:%d %H:%M:%S') 
                       for vl in exif_fields['CreateDate']]
        
        # Check for missing dates and date range
        only_dates = [vl for vl in image_dates if vl is not None]
        if len(only_dates) < n_exif:
            issues.append('missing_dates')
        
        start_dt = min(only_dates)
        end_dt = max(only_dates)
        n_days = (end_dt - start_dt).days + 1
        folder_data['start'] = start_dt
        folder_data['end'] = end_dt
        folder_data['n_days'] = n_days
    
    
    # b) Image sequence information - this is usually in MakerNotes:Sequence but sometimes seems
    #    to turn up in the file name instead. 
    
    # First look for complete data from the EXIF tag, which is in 'n N' format.
    
    if 'Sequence' in exif_fields: 
        exif_sequence = [vl if vl is None else vl.split()[0] for vl in exif_fields['Sequence']]
    else:
        exif_sequence = [None] * n_exif
        
    if 'Sequence' not in exif_fields or None in exif_fields['Sequence']:
        # Look for sequence information embedded in the file names
        regex = re.compile('\d+(?= of \d+)')
        file_sequence = [regex.search(im) for im in images]
        file_sequence = [f[0] if fl is not None else None for fl in file_sequence]
    else:
        file_sequence = [None] * n_exif
    
    # merge with exif sequence data, preferring exif
    exif_fields['Sequence'] = [xval if xval is not None else fval 
                               for xval, fval in zip(exif_sequence, file_sequence)]
    
    # Look to see if any sequences _still_ missing
    if None in exif_fields['Sequence']:
        issues.append('missing_sequence')
    
    # Add the number of images
    folder_data['n_images'] = n_exif
    
    # Add image names to image data
    exif_fields['file'] = images
    
    return {'issues': issues, 'folder_data': folder_data, 
            'image_data': exif_fields, 'other_files': other_files, 
            'image_dir': image_dir, 'keyword_tags': keyword_tags}


def gather_deployment_files(image_dirs, location, calib_dirs=[]):

    """Takes a set of image directories and a location name and returns a dictionary of the source
    and destination file name pairs, the earliest recorded image creation date (which is used to
    label the deployment) and the provided location (also used in the deployment name).
    
    Optionally, a list of directories containing calibration images can also be provided, to
    be stored in a 'CALIB' directory within the deployment directory.
    
    Args:
        image_dirs: A list of directories containing camera trap images
        location: The name of the location to be used as the deployment name
        calib: An optional list of directories of calibration images.
    
    Returns: 
        A dictionary:
        * 'files': a list of (dest, src) filename tuples
        * 'date': the earliest recorded image creation date in the image files
        * 'location': the provided location
        * 'calib': A boolean to show if calibration images folders are included
    """
    
    # Check image and calib directories exist and are directories
    input_dirs = image_dirs + calib_dirs
    bad_dir = [dr for dr in input_dirs if not os.path.isdir(dr)]
    if bad_dir:
        raise IOError('Directories not found: {}'.format(', '.join(bad_dir)))
        
    if len(set(input_dirs)) < len(input_dirs):
        raise IOError('Same folder in both image and calibration directory lists')

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()
    
    # Process the folders, collecting earliest dates and a list of file (src, dest) tuples
    dates = []
    files = []
    for this_dir in input_dirs:
        
        these_files, this_date = _process_folder(this_dir, location, et)
        if this_dir in calib_dirs:
            these_files = [(src, os.path.join('CALIB', dest)) for src, dest in these_files]
        dates.append(this_date)
        files.extend(these_files)
    
    # Look for file name collisions across the whole set
    all_new_file_names = [f[1] for f in files]
    if len(all_new_file_names) > len(set(all_new_file_names)):
        raise RuntimeError('Duplication found in new image names.')
    
    
    return {'files': files, 'date': min(dates), 'location': location, 
            'calib': True if calib_dirs else False}


def create_deployment(gathered_files, output_root):
    
    """Takes the output of running `gather_deployment_files` on a set of image folders and copies
    the set of files from the named sources to the new deployment image names within a single
    deployment folder in the 'output_root' directory. The deployment folder name is a combination
    of the provided 'location' name and the earliest date recorded in the EXIF:CreateDate tags in
    the images.
    
    Note that the function **does not delete** the source files when compiling the new deployment
    folder. The original file name of the image is stored in the destination image EXIF data in the
    PreservedFileName tag.

    Args:
        gathered_files: The output of running `gather_deployment_files`
        output_root: The location to compile the deployment folder to
    
    Returns:
        The name of the resulting deployment directory
    """
    
    # check the output root directory
    if not os.path.isdir(output_root):
        raise IOError('Output root directory not found')
    
    # get the final directory name and check it doesn't already exist
    outdir = f"{gathered_files['location']}_{gathered_files['date'].strftime('%Y%m%d')}"
    outdir = os.path.abspath(os.path.join(output_root, outdir))
    if os.path.exists(outdir):
        raise IOError('Output directory already exists:\n    {}'.format(outdir))
    else:
        os.mkdir(outdir)
        if gathered_files['calib']:
            os.mkdir(os.path.join(outdir, 'CALIB'))

    # move the files and insert the original file location into the EXIF metadata
    print('Copying files:\n', file=sys.stdout, flush=True)
    
    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()
    
    with progressbar.ProgressBar(max_value=len(gathered_files['files'])) as bar:
        for idx, (src, dst) in enumerate(gathered_files['files']):
            # Copy the file
            dst = os.path.join(outdir, dst)
            shutil.copyfile(src, dst)
            # Insert original file name into EXIF data
            tag_data = f'-XMP-xmpMM:PreservedFileName={src}'
            et.execute(b'-overwrite_original', tag_data.encode('utf-8'), exiftool.fsencode(dst))
            bar.update(idx)
    
    # tidy up
    et.terminate()
    
    return outdir


def extract_deployment_data(deployment, outfile=None):

    """Extracts the key EXIF data from a deployment folder, creating a tab-delimited output file
    holding image level data with a short header of deployment level data.
    
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

    # Check if the deployment folder and calib folder exist and store
    # in a dictionary keyed by calibration flag
    exif_dirs = {}
    if not os.path.exists(deployment) and os.path.isdir(deployment):
        raise IOError('Deployment path does not exist or is not a directory.')
    else:
        exif_dirs[0] = deployment
    
    calib_dir = os.path.join(deployment, 'CALIB')
    if os.path.exists(calib_dir) and os.path.isdir(calib_dir):
        exif_dirs[1] = calib_dir
    
    # Get the output folder
    if outfile is None:
        outfile = os.path.join(deployment, 'exif_data.dat')

    print(f'Extracting EXIF data from {deployment}', file=sys.stdout, flush=True)

    # Find images, extract EXIF data and flag as non-calibration images
    exif = []
    for calib_flag, this_dir in exif_dirs.items():
        # Get the JPEG files
        images = os.listdir(this_dir)
        images = [im for im in images if im.lower().endswith('.jpg')]
        # If there are any images, get the exif data, flag as calib or not and add to the pile
        if images:
            this_exif = et.get_metadata_batch([os.path.join(this_dir, im) for im in images])
            _ =[entry.update({'Calib': calib_flag}) for entry in this_exif]
            exif += this_exif
    
    if len(exif) == 0:
        print(f'No images found in {deployment}', file=sys.stdout, flush=True)
        return None
    
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
            # Single keywords can be loaded as a string not a list of string
            keywords = entry['Keywords']
            if isinstance(keywords, str):
                keywords = [keywords]
            # Split the strings on colons
            kw_list = [kw.split(':') for kw in keywords]
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
    n_exif = len(exif)
    
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
        
        # Check for missing location tags (Tag_15: None) and remove
        if None in locations:
            print(f'  ! Some images lack location tags.', file=sys.stderr, flush=True)
            locations = list(filter(None.__ne__, locations))
        
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
    dep_data['n_images'] = n_exif - sum(exif_fields['Calib'])
    dep_data['n_calib'] = n_exif - dep_data['n_images']
    
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
    print(f'Data written to {outfile}', file=sys.stdout, flush=True)
    et.terminate()




"""
Command line interfaces to the two functions
"""


def _process_deployment_cli():

    """
    Compiles folders of images collected from a camera trap into a single deployment folder in
    the 'output_root' directory. The deployment folder name is a combination of the provided
    'location' name and the earliest date recorded in the EXIF:CreateDate tags in the images. A set
    of folders of calibration images can also be provided, which are moved into a single CALIB
    directory within the new deployment directory.
    
    Note that the function **does not delete** the source files when compiling the new deployment
    folder.
    """
    
    desc = textwrap.dedent(_process_deployment_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)
    
    parser.add_argument('location', type=str, 
                        help='A SAFE location code from the gazetteer that will be '
                             'used in the folder and file names.')
    parser.add_argument('output_root', type=str, 
                        help='A path to the directory where the deployment folder '
                             'is to be created.')
    parser.add_argument('directories', metavar='dir', type=str, nargs='+',
                        help='Paths for each directory to be included in the deployment folder.')
    parser.add_argument('-c', '--calib', default=None, type=str, action='append',
                        help='A path to a folder of calibration images. Can be repeated to '
                             'provide more than one folder of calibration images.')
    
    args = parser.parse_args()
    
    gathered = gather_deployment_files(image_dirs=args.directories, calib_dirs=args.calib,
                                       location=args.location)
    create_deployment(gathered, output_root=args.output_root)


def _extract_deployment_data_cli():

    """
    This script takes a single deployment folder and extracts EXIF data for the deployment
    into a tab delimited file. By default, the data is written to a file `exif_data.dat` 
    within the deployment directory.
    """
    
    desc = textwrap.dedent(_extract_deployment_data_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)
    
    parser.add_argument('deployment',
                        help='A path to a deployment directory')
    parser.add_argument('-o', '--outfile', default=None,
                        help='An output file name')

    args = parser.parse_args()

    extract_deployment_data(deployment=args.deployment, outfile=args.outfile)

