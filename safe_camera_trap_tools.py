"""This module provides the Deployment class, used to manipulate and export data from SAFE
Project camera trap images. It also contains two wrapper functions to carry out data extraction
and deployment that are exposed as command line entry points in the setup.
"""

import os
import sys
import argparse
from datetime import datetime
import csv
import shutil
from itertools import groupby
from collections import OrderedDict
import textwrap
import re
import exiftool
import progressbar

DATEFIELD = 'EXIF:DateTimeOriginal'

class Deployment():
    """The Deployment class

    This class collects camera trap images from a set of directories and provides methods to:
        1. extract a standard set of EXIF fields from the images,
        2. check that the images and their EXIF data contain enough information to compile
           them into a standard deployment folder format, and
        3. create a compiled deployment folder by copying loaded images.
    """

    def __init__(self, image_dirs=None, calib_dirs=None, deployment=None):

        self.images = []
        self.calib = []
        self.sequence = []
        self.dates = []
        self.other_files = []
        self.loaded_tags = []
        self.exif_fields = None
        self.kw_tags = []
        self.location = None
        self.compilable = False
        self.compilation_errors = []
        self.deployment = ''
        self.image_dirs = []
        self.calib_dirs = []

        # Check the inputs:
        if deployment is not None and (image_dirs or calib_dirs):
            raise ValueError('Provide one of deployment or directory lists, not both')

        if deployment is not None:
            # Check the deployment exists
            if not os.path.exists(deployment) and os.path.isdir(deployment):
                raise IOError('Deployment directory not found or not a directory')

            image_dirs = [deployment]

            # Check the internal structure seems like a standard deployment
            deployment_subdirs = next(os.walk(deployment))[1]
            if len(deployment_subdirs) == 0:
                pass
            elif deployment_subdirs == ['CALIB']:
                calib_dirs = [os.path.join(deployment, 'CALIB')]
            else:
                raise IOError('Deployment directory contains unexpected directories')

            self.deployment = deployment

        # If the instance is passed image and calibration directories, populate them.
        if image_dirs is not None:
            for im_dir in image_dirs:
                self.add_directory(im_dir)
        
        if calib_dirs is not None:
            for cl_dir in calib_dirs:
                self.add_directory(cl_dir, True)

    def __str__(self):

        n_image = len(self.images)
        n_calib = sum(self.calib)

        if self.deployment:
            return (f"A standard deployment containing {n_image - n_calib} images "
                    f"and {n_calib} calibration images")

        return (f"A set of {n_image - n_calib} images and {n_calib} calibration images "
                f"from {len(self.image_dirs)} image directories and "
                f"{len(self.calib_dirs)} calibration directories")

    def add_directory(self, src_dir, calib=False):
        """Adds the JPEG images in a directory to a deployment, optionally flagging them
        as calibration images.

        Args:
            src_dir: A path to a folder containing camera trap JPEG images
            calib: A boolean indicating if these are calibration images
        """

        if not os.path.exists(src_dir) and os.path.isdir(src_dir):
            raise IOError(f'Path does not exist or is not a directory: {src_dir}')

        files = next(os.walk(src_dir))[2]
        images = [fl for fl in files if fl.lower().endswith('jpg')]
        n_images = len(images)
        other_files = list(set(files) - set(images))
        calib_vals = [calib] * n_images

        self.images.extend([os.path.join(src_dir, im) for im in images])
        self.calib.extend(calib_vals)
        self.other_files.extend(other_files)

        if calib:
            self.calib_dirs.extend([src_dir])
        else:
            self.image_dirs.extend([src_dir])

    def check_compilable(self, location=None):

        """Check if the images in a deployment can be compiled into a standard deployment.

        This method checks if the images loaded in a Deployment instance can be compiled into
        a deployment directory. This is simply ensuring that there is enough information to
        create standard camera trap image names: "location_YYYYMMDD_HHMMSS_N.jpg". So, for all
        images loaded into a Deployment:
            - There must be an EXIF:DateTimeOriginal entry in the EXIF data for every file.
            - Any location tags in the images must be consistent. These are stored in the
              IPTC:Keywords EXIF data with the '15' tag. Missing location tags are acceptable.
            - image sequence: The function reads any EXIF sequence data and supplements that with
              filename sequence data if the EXIF sequence is missing or incomplete.

        A location can be provided and is necessary if _no_ image contains location information.
        Provided locations are checked for consistency with EXIF locations.

        Returns:
            A boolean indicating success or failure
        """

        # reset previous attempts
        self.location = location
        self.compilation_errors = []

        if not self.images:
            self.compilation_errors.append('No images in deployment')
            return False

        # Load the validation data for the images
        validate_tags = [DATEFIELD, "MakerNotes:Sequence", "IPTC:Keywords"]
        self.exif_fields = self._read_exif(self.images, validate_tags)
        self.loaded_tags = validate_tags
        self._unpack_keywords()

        # Get dates and check they are complete
        self._get_dates()
        if None in self.dates:
            self.compilation_errors.append('Missing dates')

        # Check location data
        if 'Keyword_15' not in self.kw_tags:
            exif_locations = set([None])
        elif all(x is None for x in self.exif_fields['Keyword_15']):
            exif_locations = set([None])
        else:
            exif_locations = set(self.exif_fields['Keyword_15'])

        real_exif_locations = list(exif_locations - set([None]))
        n_loc = len(real_exif_locations)
        loc_error = None

        if n_loc > 1:
            loc_error = f"Inconsistent source locations: {','.join(real_exif_locations)}"
        elif self.location is not None and n_loc == 1 and real_exif_locations[0] != self.location:
            loc_error = f"Location {self.location} does not match EXIF {real_exif_locations[0]}"
        elif self.location is None and n_loc == 0:
            loc_error = 'No location tags in files and no location argument provided'
        elif self.location is None:
            self.location = real_exif_locations[0]
        
        if loc_error is not None:
            self.compilation_errors.append(loc_error)

        # Get image sequence information:
        # 1) Get data from the EXIF tag, which is in 'n N' format.
        exif_sequence = [vl if vl is None else vl.split()[0]
                         for vl in self.exif_fields['MakerNotes:Sequence']]

        # 2) If needed, supplement with sequence information embedded in the file names as
        #    'n of N' and extract n
        if None in exif_sequence:
            regex = re.compile('\d+(?= of \d+)')
            file_sequence = [regex.search(im) for im in self.images]
            file_sequence = [fl[0] if fl is not None else None for fl in file_sequence]

            # merge with exif sequence data, preferring exif
            exif_sequence = [xval if xval is not None else fval
                             for xval, fval in zip(exif_sequence, file_sequence)]

        # 3) Lastly, if all the dates are available, make one up.
        if None not in self.dates and None in exif_sequence:
            # Find the datetimes of missing sequence values
            dt_seq = zip(self.dates, exif_sequence)
            missing_seq = [(idx, dt)  for idx, (dt, seq) in enumerate(dt_seq) if seq is None]

            # Now find groups of shared dates
            missing_seq.sort(key=lambda x: x[1])
            missing_seq = groupby(missing_seq, key=lambda x: x[1])
            for grp, vals in missing_seq:
                # Create a dummy sequence (X1, X2, ..., Xn) for this datetime to replace None
                vals = list(vals)
                new_seq = ['X' + str(n + 1) for n in range(len(vals))]
                for (idx, date), new_seq in zip(vals, new_seq):
                    exif_sequence[idx] = new_seq

        self.sequence = exif_sequence

        if self.compilation_errors:
            print(f"Compilation failed: {','.join(self.compilation_errors)}",
                  file=sys.stdout, flush=True)
            return False

        self.compilable = True
        return True

    def compile(self, output_root):

        """Compile a set of images into a standard deployment directory.

        Once a set of images have passed check_compilable, this function copies all of the
        source files into a new deployment directory. Note that the function **does not delete**
        the source files when compiling the new deployment folder. The original file name of the
        image is stored in the destination image EXIF data in the XMP:PreservedFileName tag.

        Args:
            output_root: The location to compile the deployment folder.

        Returns:
            The name of the compiled deployment folder
        """

        if not self.compilable and not self.compilation_errors:
            raise RuntimeError("check_compilable has not been run")

        if not self.compilable:
            raise RuntimeError(f"Compilation failed : {', '.join(self.compilation_errors)}")

        # check the output root directory
        if not os.path.isdir(output_root):
            raise IOError('Output root directory not found')

        # create the deployment directory
        deployment_dir = f"{self.location}_{min(self.dates).strftime('%Y%m%d')}"
        dep_path = os.path.abspath(os.path.join(output_root, deployment_dir))

        if os.path.exists(dep_path):
            raise IOError(f'Output directory already exists: {deployment_dir}')

        os.mkdir(dep_path)

        # Get the destination file names
        dest_files = [f'{self.location}_{dt.strftime("%Y%m%d_%H%M%S")}_{seq}.jpg'
                      for dt, seq in zip(self.dates, self.sequence)]

        # Create a calib directory if needed and extend the path for those images
        if True in self.calib:
            os.mkdir(os.path.join(dep_path, 'CALIB'))
            dest_files = [os.path.join('CALIB', fl) if cl else fl
                          for fl, cl in zip(dest_files, self.calib)]

        # Move the files and insert the original file location into the EXIF metadata
        print('Copying files:\n', file=sys.stdout, flush=True)

        # get an exifread.ExifTool instance to insert the original filename
        extl = exiftool.ExifTool()
        extl.start()

        with progressbar.ProgressBar(max_value=len(self.images)) as prog_bar:
            for idx, (src, dst) in enumerate(zip(self.images, dest_files)):
                # Copy the file
                dst = os.path.join(dep_path, dst)
                shutil.copyfile(src, dst)
                # Insert original file name into EXIF data. The execute method needs byte inputs.
                tag_data = f'-XMP-xmpMM:PreservedFileName={src}'
                extl.execute(b'-overwrite_original', tag_data.encode('utf-8'),
                             exiftool.fsencode(dst))
                prog_bar.update(idx)

        # tidy up
        extl.terminate()

        return dep_path

    def extract_data(self, outfile=None):
        """Extract EXIF data from images in a deployment

        Extracts the key EXIF data from a deployment, creating a tab-delimited output file
        holding image level data with a short header of deployment level data. If the
        instance is of a standard deployment (created by using Deployment(deployment=path))
        then the outfile defaults to 'exif_dat.dat' within the deployment folder. Otherwise
        an outfile has to be provided, since the image and calib folder structures are unknown.

        For a standard deployment, the output file includes file names relative to the
        deployment folder but for images loaded using image_dirs and calib_dirs, full paths are
        reported.

        Args:
            outfile: A path to a file to hold the extracted data as tab delimited text.
        """

        if len(self.images) == 0:
            raise RuntimeError('No images loaded in deployment')

        # Get the output folder
        if outfile is None and self.deployment:
            outfile = os.path.join(self.deployment, 'exif_data.dat')
        elif outfile is None:
            raise ValueError('Need to provide outfile.')

        print('Extracting EXIF data ', file=sys.stdout, flush=True)

        # Find images, extract EXIF data and flag as non-calibration images
        # Reduce to tags used in rest of the script, filling in blanks and simplifying tag names
        camera_tags = ['EXIF:Make', 'EXIF:Model', 'MakerNotes:SerialNumber',
                       'MakerNotes:FirmwareDate', 'File:ImageHeight', 'File:ImageWidth']
        image_tags = ["File:FileName", "EXIF:DateTimeOriginal", "EXIF:ExposureTime",
                      "EXIF:ISO", "EXIF:Flash", "MakerNotes:InfraredIlluminator",
                      "MakerNotes:MotionSensitivity", "MakerNotes:AmbientTemperature",
                      "EXIF:SceneCaptureType", "MakerNotes:Sequence", "MakerNotes:TriggerMode",
                      'IPTC:Keywords']
        target_tags = camera_tags + image_tags

        self.exif_fields = self._read_exif(self.images, target_tags)
        self.loaded_tags = target_tags
        self._unpack_keywords()

        # REPORTING AND VALIDATION
        # DEPLOYMENT level data
        print('Checking for consistent deployment data', file=sys.stdout, flush=True)
        dep_data = OrderedDict()

        # A) Check for consistent camera data
        for long_tg, short_tg in self._strip_exif_groups(camera_tags):
            vals = set(self.exif_fields[long_tg])
            vals = ['NA' if vl is None else vl for vl in vals]
            n_vals = len(vals)
            dep_data[short_tg] = ', '.join([str(v) for v in vals])

            if n_vals > 1:
                print(f"  ! {short_tg} is not consistent: {vals}", file=sys.stderr, flush=True)


        # B) Extract date information and put it back in the exif data
        self._get_dates()
        self.exif_fields[DATEFIELD] = self.dates

        # check completeness
        date_bad = [vl is None for vl in self.dates]
        valid_dates = [vl for vl in self.dates if vl is not None]
        n_img = len(self.images)

        if all(date_bad):
            print('  ! No {DATEFIELD} tags found', file=sys.stderr, flush=True)
        else:
            if any(date_bad):
                print(f'  ! {DATEFIELD} tags not complete: {n_img - sum(date_bad)}/n_img',
                      file=sys.stderr, flush=True)

            # get the date range
            start_dt = min(valid_dates)
            end_dt = max(valid_dates)
            n_days = (end_dt - start_dt).days + 1
            dep_data['start'] = str(start_dt)
            dep_data['end'] = str(end_dt)
            dep_data['n_days'] = n_days

        # C) Check location data (only keyword tag that should be constant)
        if 'Keyword_15' not in self.kw_tags:
            print('  ! No location tags (15) found', file=sys.stderr, flush=True)
        else:
            # Get the unique tagged locations
            locations = set(self.exif_fields['Keyword_15'])

            # Check for missing location tags (Keyword_15: None) and remove
            if None in locations:
                print(f'  ! Some images lack location tags.', file=sys.stderr, flush=True)
                locations -= set([None])

            if len(locations) > 1:
                locations = ', '.join(locations)
                print(f'  ! Location tags (15) not internally consistent: {locations}',
                      file=sys.stderr, flush=True)
            else:
                locations = list(locations)[0]

            # Are they consistent with the deployment folder
            if self.deployment:
                match_folder = [os.path.basename(self.deployment).startswith(l) for l in locations]

                if not any(match_folder):
                    print('  ! Location tags (15) do not match deployment folder.',
                          file=sys.stderr, flush=True)

            dep_data['location'] = locations

        # Add the number of images
        dep_data['n_images'] = n_img - sum(self.calib)
        dep_data['n_calib'] = sum(self.calib)

        # print to screen to report
        print('Deployment data:', file=sys.stdout, flush=True)
        dep_lines = [f'{ky}: {vl}' for ky, vl in dep_data.items()]
        print(*['    ' + d +'\n' for d in dep_lines], file=sys.stdout, flush=True)

        # IMAGE level data
        # report on keyword tag completeness:
        if not self.kw_tags:
            print(' ! No Image keyword tags found', file=sys.stderr, flush=True)
        else:
            print('Image tag counts:', file=sys.stdout, flush=True)
            for tag in self.kw_tags:
                n_found = sum([vl is not None for vl in self.exif_fields[tag]])
                print(f'    {tag:10}{n_found:6}', file=sys.stdout, flush=True)

        # WRITE data to files
        with open(outfile, 'w') as outf:
            # Header containing constant deployment data
            outf.write(f'Header length: {len(dep_lines) + 1}\n')
            outf.writelines(ln + '\n' for ln in dep_lines)

        with open(outfile, 'a') as outf:
            # Tab delimited table of image data
            writer = csv.writer(outf, delimiter='\t', lineterminator='\n')

            # Insert file name and calib status into dictionary
            if self.deployment:
                file_names = [os.path.basename(im) for im in self.images]
                file_names = [os.path.join('CALIB', im) if cl else im
                              for im, cl in zip(file_names, self.calib)]
            else:
                file_names = [os.path.abspath(im) for im in self.images]

            output_data = OrderedDict([('File', file_names), ('Calib', self.calib)])

            # Add the fields to the output data directory, stripping EXIF groups
            tags = self._strip_exif_groups(self.exif_fields)
            for long_tag, short_tag in tags:
                output_data[short_tag] = self.exif_fields[long_tag]

            data = zip(*output_data.values())
            writer.writerow(output_data.keys())
            writer.writerows(data)

        # tidy up
        print(f'Data written to {outfile}', file=sys.stdout, flush=True)

    @staticmethod
    def _strip_exif_groups(tags):
        """Simplifies tag names by stripping EXIF groups. It converts a list of tags to a list
        of 2-tuples of provided and simplified names.
        """

        exif_group = re.compile('[A-z]+:')
        tags = [(vl, exif_group.sub('', vl)) for vl in tags]

        return tags

    @staticmethod
    def _convert_keywords(keywords):
        """Unpacks a list of EXIF keywords into a dictionary.

        The keywords are integers, where the tag numbers can be repeated. The process below
        combines duplicate tag numbers and strips whitespace padding. For example:
            ['15: E100-2-23', '16: Person', '16: Setup', '24: Phil']
        goes to
            {15: 'E100-2-23', 16: 'Person, Setup', 24: 'Phil'}

        Returns:
            A dictionary of keyword values.
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
            kw_dict[key] = ', '.join(vl[1].strip() for vl in vals)

        return kw_dict

    @staticmethod
    def _read_exif(files, tags):
        """Read EXIF tags for a list of files.

        It returns an ordered dictionary, ordered by the original tag list, of EXIF tag values
        for each of the provided files. Empty tags for a file and tags that are missing completely
        across all files are filled with None.

        Args:
            files: A list of file names
            tags: A list of EXIF tag names. These are shortened to remove EXIF group prefixes.

        Returns:
            An ordered dict keyed by tag names.
        """

        # get an exifread.ExifTool instance and read, which returns a list of dictionaries
        # of tag values by file
        extl = exiftool.ExifTool()
        extl.start()
        exif = extl.get_tags_batch(tags, files)
        extl.terminate()

        # Convert list of dictionaries to a dictionary of lists, using OrderedDict to
        # preserve the field order of the tags when the data is written to file.
        exif_fields = OrderedDict([(tg, [dic.get(tg, None) for dic in exif]) for  tg in tags])

        return exif_fields

    def _get_dates(self):
        """Converts EXIF dates to datetime.datetime and stores in self.dates"""

        if not self.exif_fields:
            raise RuntimeError('No EXIF data loaded')
        if DATEFIELD not in self.exif_fields:
            raise RuntimeError(f'{DATEFIELD} not in loaded EXIF data')
        
        # EXIF should have a consistent datetime format of "YYYY:mm:dd HH:MM:SS"
        # but we do need to handle corrupt dates.
        def _date_conv(dt):
            
            try:
                dt = datetime.strptime(dt, '%Y:%m:%d %H:%M:%S')
            except ValueError:
                dt = None
            
            return dt
        
        self.dates = [_date_conv(vl) if vl is not None else None
                      for vl in self.exif_fields[DATEFIELD]]

    def _unpack_keywords(self):
        """Unpack EXIF keywords

        Unpacks the IPTC:Keywords tag in data loaded into self.exif_fields into new fields
        keyed by keyword tag number n as 'Keyword_n'. If there is no Keywords field, exif_fields
        is unchanged; otherwise the keyword tags are added at the end in numeric order and the
        Keywords fields is removed. It also populates the self.kw_tags attribute with the
        resulting keyword field keys.
        """

        kw_field = 'IPTC:Keywords'

        if kw_field in self.exif_fields or any(x is not None for x in self.exif_fields[kw_field]):

            # Convert the entries from a list to a dict keyed by tag
            kw_data = [self._convert_keywords(kw) for kw in self.exif_fields[kw_field]]

            # Find the common set
            keyword_tags = [list(d.keys()) for d in kw_data]
            keyword_tags = list({tg for tag_list in keyword_tags for tg in tag_list})

            # now sort into numeric order for clean reporting. Mostly, tags are integer
            # but there are sometimes bracketed values, e.g. 1(2)
            leading_digits = re.compile('^\d+')
            bracketed_digit = re.compile('(?<=\()\d+(?=\))')

            keyword_ld = [leading_digits.search(x) for x in keyword_tags]
            keyword_bd = [bracketed_digit.search(x) for x in keyword_tags]

            if any([vl is None for vl in keyword_ld]):
                raise ValueError(f"Could not parse keyword tags: {', '.join(keyword_tags)}")

            keyword_ld = [int(x[0]) for x in keyword_ld]
            keyword_bd = [int(x[0]) if x is not None else 0 for x in keyword_bd]

            keyword_tags = list(zip(keyword_tags, keyword_ld, keyword_bd))
            keyword_tags.sort(key=lambda x: (x[1], x[2]))
            keyword_tags = [tg[0] for tg in keyword_tags]

            # Get the str version of the keyword tags
            keyword_tags_str = ['Keyword_' + str(kw_tag) for kw_tag in keyword_tags]
            keyword_tags = list(zip(keyword_tags, keyword_tags_str))

            # Extract the data for each tag from each file and add in order to self.exif_fields,
            # using dict.get(ky, None) to fill in missing tags
            for kw_num, kw_str in keyword_tags:
                self.exif_fields[kw_str] = [rw.get(kw_num, None) for rw in kw_data]

            self.kw_tags = keyword_tags_str

        if kw_field in self.exif_fields:
            del self.exif_fields[kw_field]


"""
Command line interfaces
"""


def _process_deployment_cli():

    """
    Compiles folders of images collected from a camera trap into a single deployment folder in
    the 'output_root' directory. The deployment folder name is a combination of the location
    name and the earliest date recorded in the EXIF:DateTimeOriginal tags in the images. A set
    of folders of calibration images can also be provided, which are moved into a single CALIB
    directory within the new deployment directory.

    A location name can be provided. This will be checked to see if it is consistent with any
    stored locations in the image keywords. If no location tags are present in the images, then
    a location must be provided to generate the deployment directory name, otherwise the location
    used in the image tags can be used.

    Note that the function **does not delete** the source files when compiling the new deployment
    folder.
    """

    desc = textwrap.dedent(_process_deployment_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)

    parser.add_argument('output_root', type=str,
                        help='A path to the directory where the deployment folder '
                             'is to be created.')
    parser.add_argument('images', type=str, nargs='+',
                        help='Paths for each image directory to be included.')
    parser.add_argument('-c', '--calib', default=None, type=str, action='append',
                        help='A path to a folder of calibration images. Can be repeated to '
                             'provide more than one folder of calibration images.')
    parser.add_argument('-l', '--location', type=str, default=None,
                        help='A SAFE location code to be checked against any location tags '
                             'tags in the images and used for the deployment folder.')

    args = parser.parse_args()

    dep = Deployment(image_dirs=args.images, calib_dirs=args.calib)
    can_compile = dep.check_compilable(location=args.location)

    if can_compile:
        dep.compile(output_root=args.output_root)


def _extract_exif_data_cli():

    """
    This script extracts EXIF data from camera trap images. The most common use is with a single
    standard deployment directory, but EXIF data can also be read from a set of image and
    calibration directories. Data is written into a tab delimited file: for standard deployments
    the data is written by default to a file `exif_data.dat` within the deployment directory. If
    multiple directories are provided, an output file has to be provided.
    """

    desc = textwrap.dedent(_extract_exif_data_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)

    parser.add_argument('deployment', nargs='?',
                        help='A path to a deployment directory')
    parser.add_argument('-o', '--outfile', default=None,
                        help='An output file name')
    parser.add_argument('-i', '--image_dirs', default=[], type=str, action='append',
                        help='A path to a folder of images. Can be repeated to '
                             'provide more than one folder of images.')
    parser.add_argument('-c', '--calib_dirs', default=[], type=str, action='append',
                        help='A path to a folder of calibration images. Can be repeated to '
                             'provide more than one folder of calibration images.')

    args = parser.parse_args()

    dep = Deployment(image_dirs=args.image_dirs, calib_dirs=args.calib_dirs,
                     deployment=args.deployment)
    dep.extract_data(outfile=args.outfile)
