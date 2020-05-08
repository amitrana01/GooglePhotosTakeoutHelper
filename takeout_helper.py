import os
import shutil
import piexif
import json
import re
from datetime import datetime
import argparse

parser = argparse.ArgumentParser(
    prog='Photos takeout helper',
    usage='python3 photos_helper.py -i [INPUT TAKEOUT FOLDER] -o [OUTPUT FOLDER]',
    description=
    'This script takes all of your photos form Google Photos takeout, '
    'fixes their exif DateTime data (when they were taken) and file creation date,'
    'and then copies it all to one folder.'
)
parser.add_argument(
    '-i', '--input-folder',
    type=str,
    required=True,
    help='Input folder with all stuff form Google Photos takeout zip(s)'
)
parser.add_argument(
    '-o', '--output-folder',
    type=str,
    required=False,
    default='ALL_PHOTOS',
    help='Output folders which in all photos will be placed in'
)
parser.add_argument(
    '--keep-duplicates',
    action='store_true',
    help="Don't remove duplicates. Disclaimer: "
         "duplicates will have trouble to find correct creation date, "
         "and it may not be accurate"
)
parser.add_argument(
    '--dont-fix',
    action='store_true',
    help="Don't try to fix Dates. I don't know why would you not want to do that, but ok"
)
parser.add_argument(
    '--dont-copy',
    action='store_true',
    help="Don't copy files to target folder. I don't know why would you not want to do that, but ok"
)
parser.add_argument(
    "--divide-to-dates",
    action='store_true',
    help="Create folders and subfolders based on the date the photos were taken"
         "If you use the --dont-copy flag, or the --dont-fix flag, this is useless"
)
args = parser.parse_args()

print('DISCLAIMER!')
print("Before running this script, you need to cut out all folders that aren't dates")
print("That is, all album folders, and everything that isn't named")
print('2016-06-16 (or with "#", they are good)')
print('See README.md or --help on why')
print("(Don't worry, your photos from albums are already in some date folder)")
print()
print('Type "yes i did that" to comfirm:')
response = input()
if response == 'yes i did that':
    print('Heeeere we go!')
else:
    print('Ok come back when you do this')

PHOTOS_DIR = args.input_folder
FIXED_DIR = args.output_folder

TAG_DATE_TIME_ORIGINAL = piexif.ExifIFD.DateTimeOriginal
TAG_DATE_TIME_DIGITIZED = piexif.ExifIFD.DateTimeDigitized
TAG_DATE_TIME = 306
TAG_PREVIEW_DATE_TIME = 50971

photo_formats = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff']
video_formats = ['.mp4', '.gif', '.mov', '.webm']

os.makedirs(FIXED_DIR, exist_ok=True)


def for_all_files_recursive(
  dir,
  file_function=lambda fo, fi: True,
  folder_function=lambda fo: True,
  filter_fun=lambda file: True
):
    for file in os.listdir(dir):
        file = dir + '/' + file
        if os.path.isdir(file):
            folder_function(file)
            for_all_files_recursive(file, file_function, folder_function, filter_fun)
        elif os.path.isfile(file):
            if filter_fun(file):
                file_function(dir, file)
        else:
            print('Found something weird...')
            print(file)


def is_photo(file):
    what = os.path.splitext(file.lower())[1]
    if what not in photo_formats:
        return False
    return True


def is_video(file):
    what = os.path.splitext(file.lower())[1]
    if what not in video_formats:
        return False
    return True


# PART 1: removing duplicates

# THIS IS PARTLY COPIED FROM STACKOVERFLOW
# THANK YOU @Todor Minakov
def find_duplicates(path, filter_fun=lambda file: True):
    hashes_by_size = {}
    # Excluding original files (or first file if original not found)
    duplicates = []

    for dirpath, dirnames, filenames in os.walk(path):
        for filename in filenames:
            if not filter_fun(filename):
                continue
            full_path = os.path.join(dirpath, filename)
            try:
                # if the target is a symlink (soft one), this will
                # dereference it - change the value to the actual target file
                full_path = os.path.realpath(full_path)
                file_size = os.path.getsize(full_path)
            except (OSError,):
                # not accessible (permissions, etc) - pass on
                continue

            duplicate = hashes_by_size.get(file_size)

            if duplicate:
                hashes_by_size[file_size].append(full_path)
            else:
                hashes_by_size[file_size] = []  # create the list for this file size
                hashes_by_size[file_size].append(full_path)

    for size in hashes_by_size.keys():
        if len(hashes_by_size[size]) > 1:
            original = None
            for filename in hashes_by_size[size]:
                if not re.search(r'\(\d+\).', filename):
                    original = filename
            if original is None:
                original = hashes_by_size[size][0]

            dups = hashes_by_size[size].copy()
            dups.remove(original)
            duplicates += dups

    return duplicates


# Removes all duplicates in folder
def remove_duplicates(dir):
    duplicates = find_duplicates(dir, lambda f: (is_photo(f) or is_video(f)))
    for file in duplicates:
        os.remove(file)
    return True


# PART 2: Fixing metadata and date-related stuff

# Returns json dict
def find_json_for_file(dir, file):
    potential_json = file + '.json'
    if os.path.isfile(potential_json):
        try:
            with open(potential_json, 'r') as f:
                dict = json.load(f)
            return dict
        except:
            raise FileNotFoundError('Couldnt find json for file: ' + file)
    else:
        raise FileNotFoundError('Couldnt find json for file: ' + file)


# Returns date in 2019:01:01 23:59:59 format
def get_date_from_folder_name(dir):
    dir = os.path.basename(os.path.normpath(dir))
    dir = dir[:10].replace('-', ':') + ' 12:00:00'
    return dir


def set_creation_date_from_str(file, str_datetime):
    timestamp = datetime.strptime(
        str_datetime,
        '%Y:%m:%d %H:%M:%S'
    ).timestamp()
    os.utime(file, (timestamp, timestamp))


def set_creation_date_from_exif(file):
    exif_dict = piexif.load(file)
    tags = [['0th', TAG_DATE_TIME], ['Exif', TAG_DATE_TIME_ORIGINAL], ['Exif', TAG_DATE_TIME_DIGITIZED]]
    datetime_str = None
    for tag in tags:
        try:
            datetime_str = exif_dict[tag[0]][tag[1]].decode('UTF-8')
            break
        except KeyError:
            pass
    if datetime_str is None:
        raise IOError('No DateTime in given exif')
    set_creation_date_from_str(file, datetime_str)


def set_file_exif_date(file, creation_date):
    try:
        exif_dict = piexif.load(file)
    except (piexif.InvalidImageDataError, ValueError):
        exif_dict = {'0th': {}, 'Exif': {}}

    creation_date = creation_date.encode('UTF-8')
    exif_dict['0th'][TAG_DATE_TIME] = creation_date
    exif_dict['Exif'][TAG_DATE_TIME_ORIGINAL] = creation_date
    exif_dict['Exif'][TAG_DATE_TIME_DIGITIZED] = creation_date

    try:
        piexif.insert(piexif.dump(exif_dict), file)
    except ValueError as e:
        print('Couldnt insert exif!')
        print(e)


def get_date_str_from_json(json):
    return datetime.fromtimestamp(
        int(json['photoTakenTime']['timestamp'])
    ).strftime('%Y:%m:%d %H:%M:%S')


# Fixes ALL metadata, takes just file and dir and figures it out
def fix_metadata(dir, file):
    print(file)

    has_nice_date = False
    try:
        set_creation_date_from_exif(file)
        has_nice_date = True
    except (piexif.InvalidImageDataError, ValueError) as e:
        print(e)
        print(f'No exif for {file}')
    except IOError:
        print('No creation date found in exif!')
    print('Trying to find json...')

    try:
        google_json = find_json_for_file(dir, file)
        date = get_date_str_from_json(google_json)
        set_file_exif_date(file, date)
        set_creation_date_from_str(file, date)
        has_nice_date = True
        return
    except FileNotFoundError:
        print('Couldnt find json for file :/')

    if has_nice_date:
        return

    print('Last chance, coping folder name as date...')
    date = get_date_from_folder_name(dir)
    set_file_exif_date(file, date)
    set_creation_date_from_str(file, date)
    return True


# PART 3: Copy all photos and videos to target folder

def copy_to_target(dir, file):
    if is_photo(file) or is_video(file):
        shutil.copy2(file, FIXED_DIR)
    return True


def copy_to_target_and_divide(dir, file):
    creation_date = os.path.getmtime(file)
    date = datetime.fromtimestamp(creation_date)

    new_path = f"{FIXED_DIR}/{date.year}/{date.month:02}/"
    os.makedirs(new_path, exist_ok=True)
    shutil.copy2(file, new_path)
    return True


if not args.keep_duplicates:
    print('=====================')
    print('Removing duplicates...')
    print('=====================')
    for_all_files_recursive(
        dir=PHOTOS_DIR,
        folder_function=remove_duplicates
    )
if not args.dont_fix:
    print('=====================')
    print('Fixing files metadata and creation dates...')
    print('=====================')
    for_all_files_recursive(
        dir=PHOTOS_DIR,
        file_function=fix_metadata,
        filter_fun=lambda f: (is_photo(f) or is_video(f))
    )
if not args.dont_fix and not args.dont_copy and args.divide_to_dates:
    print('=====================')
    print('Creating subfolders and dividing files based on date...')
    print('=====================')
    for_all_files_recursive(
        dir=PHOTOS_DIR,
        file_function=copy_to_target_and_divide,
        filter_fun=lambda f: (is_photo(f) or is_video(f))
    )
elif not args.dont_copy:
    print('=====================')
    print('Coping all files to one folder...')
    print('=====================')
    for_all_files_recursive(
        dir=PHOTOS_DIR,
        file_function=copy_to_target,
        filter_fun=lambda f: (is_photo(f) or is_video(f))
    )

print()
print('DONE! FREEDOM!')
print()
