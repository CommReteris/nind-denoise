#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
@author: Huy Hoang

Denoise the raw image denoted by <filename> and save the results.

Usage:
    denoise.py [-o <outpath> | --output-path=<outpath>] [-e <e> | --extension=<e>]
                [-d <darktable> | --dt=<darktable>] [-g <gmic> | --gmic=<gmic>] [ -q <q> | --quality=<q>]
                [--nightmode ] [ --no_deblur ] [ --debug ] [ --sigma=<sigma> ] [ --iterations=<iter> ]
                [-v | --verbose] <raw_image>
    denoise.py (help | -h | --help)
    denoise.py --version

Options:

  -o <outpath> --output-path=<outpath>  Where to save the result (defaults to current directory).
  -e <e> --extension=<e>                Output file extension. Supported formats are ....? [default: jpg].
  --dt=<darktable>                      Path to darktable-cli. Use this only if not automatically found.
  -g <gmic> --gmic=<gmic>               Path to gmic. Use this only if not automatically found.
  -q <q> --quality=<q>                  JPEG compression quality. Lower produces a smaller file at the cost of more artifacts. [default: 90].
  --nightmode                           Use for very dark images. Normalizes brightness (exposure, tonequal) before denoise [default: False].
  --no_deblur                           Do not perform RL-deblur [default: false].
  --debug                               Keep intermedia files.
  --sigma=<sigma>                       sigma to use for RL-deblur. Acceptable values are ....? [default: 1].
  --iterations=<iter>                   Number of iterations to perform during RL-deblur. Suggest keeping this to ...? [default: 10].

  -v --verbose
  --version                             Show version.
  -h --help                             Show this screen.
"""
import copy
import io
import os
import pathlib
import subprocess
import sys

import exiv2
import yaml
from bs4 import BeautifulSoup
from docopt import docopt

# define RAW extensions
valid_extensions = [
    '.' + item.lower()
    if item[0] != '.'
    else item.lower()
    for item in
    ['3FR', 'ARW', 'SR2', 'SRF', 'CR2', 'CR3', 'CRW', 'DNG', 'ERF', 'FFF', 'MRW', 'NEF', 'NRW', 'ORF', 'PEF', 'RAF',
     'RW2']
]


def check_good_input(path: pathlib.Path, extensions=None) -> bool:
    """
    Check whether the given path is a valid file with one of the specified extensions.

    This function determines if the provided `path` is a file and has an extension that matches any in the `extensions` list. If the path does not exist, or it exists but is not a file, or its extension is not supported, the function returns False. Otherwise, it returns True.

    :param path: The path to check.
    :type path: pathlib.Path
    :param extensions: A list of acceptable file extensions (without leading dots) or a single string representing one such extension.
    :type extensions: Union[str, List[str]]
    :return: True if the path is a valid file with an accepted extension; False otherwise.
    :rtype: bool

    :raises AssertionError: If `extensions` is not of type list.

    .. note:: This function prints informative messages to standard output for paths that do not meet the criteria."""
    extensions = [extensions] if type(extensions) is str else extensions
    assert type(extensions) == list

    if not path.is_file():
        print("This isn't a file: ", path, ", ")
        if not path.exists():
            print("In fact, it doesn't exist. ")
        print("Either way, I'm skipping it. \n")
        return False
    elif path.suffix.lower() not in extensions:
        if path.suffix.lower() != '.xmp':
            print("Not a (supported) RAW file: ", path, ", skipping.")
        return False
    else:
        return True

def clone_exif(src_file: pathlib.Path, dst_file: pathlib.Path, verbose=False) -> None:
    """
    Clone the EXIF metadata from one image file to another.

    This function reads the EXIF metadata from a source image file and copies it
    to a destination image file using the Exiv2 library. It handles potential errors
    by printing them if verbose mode is enabled, and raises the exception afterward.

    :param src_file: The path to the source image file.
    :type src_file: pathlib.Path

    :param dst_file: The path to the destination image file.
    :type dst_file: pathlib.Path

    :param verbose: If True, prints messages about the process and any errors that occur.
    :type verbose: bool

    :return: This function does not return a value.
    :rtype: None
    """
    try:
        src_image = exiv2.ImageFactory.open(str(src_file))
        src_image.readMetadata()

        dst_image = exiv2.ImageFactory.open(str(dst_file))
        dst_image.setExifData(src_image.exifData())
        dst_image.writeMetadata()
    except Exception as e:
        if verbose:
            print(f"An error occurred while copying EXIF data: {e}")
        raise

    if verbose:
        print(f'Copied EXIF from {src_file} to {dst_file}')

def read_config(config_path='./src/config/operations.yaml', _nightmode=False, verbose=False) -> dict:
    """
    Reads a configuration file and optionally modifies it for night mode.

    :param config_path: Path to the configuration file.
    :type config_path: str

    :param _nightmode: Flag indicating whether to apply night mode settings.
    :type _nightmode: bool

    :param verbose: Flag indicating whether to print verbose output.
    :type verbose: bool

    :return: The parsed and optionally modified configuration data.
    :rtype: dict
    """
    with io.open(config_path, 'r', encoding='utf-8') as instream:
        var = yaml.safe_load(instream)
    if _nightmode:
        if verbose:
            print("\nUpdating ops for nightmode ...")
        nightmode_ops = ['exposure', 'toneequal']
        var["operations"]["first_stage"].extend(nightmode_ops)
        for op in nightmode_ops:
            var["operations"]["second_stage"].remove(op)
    return var

def parse_darktable_history_stack(_input_xmp: pathlib.Path, config: dict, verbose=False):
    """
    :param verbose:
    :type verbose:
    :param _input_xmp:
    :type _input_xmp:
    """
    operations = config["operations"]
    with _input_xmp.open() as f:
        sidecar_xml = f.read()
    sidecar = BeautifulSoup(sidecar_xml, "xml")
    # read the history stack
    history = sidecar.find('darktable:history')
    history_org = copy.copy(history)
    history_ops = history.find_all('rdf:li')
    # sort history ops
    history_ops.sort(key=lambda tag: int(tag['darktable:num']))
    # remove ops not listed in operations["first_stage"]
    for op in reversed(history_ops):
        if op['darktable:operation'] not in operations['first_stage']:
            # op['darktable:enabled'] = "0"
            op.extract()  # remove the op completely
            if verbose:
                print("--removed: ", op['darktable:operation'])
        else:
            # for "flip": don't remove, only disable
            if op['darktable:operation'] == 'flip':
                op['darktable:enabled'] = "0"
                if verbose:
                    print("default:    ", op['darktable:operation'])
    if _input_xmp.with_suffix('.s1.xmp').is_file():
        _input_xmp.with_suffix('.s1.xmp').unlink()
    _input_xmp.with_suffix('.s1.xmp').touch(exist_ok=False)
    with _input_xmp.with_suffix('.s1.xmp').open('w') as first_stage_xmp_file:
        first_stage_xmp_file.write(sidecar.prettify())
    # restore the history stack to original
    history.replace_with(history_org)
    history_ops = history_org.find_all('rdf:li')
    """
        remove ops not listed in operations["second_stage"]
        unknown ops NOT in operations["first_stage"] AND NOT in operations["second_stage"], default to keeping them
        in 1    : N   N   Y   Y
        in 2    : N   Y   N   Y
        action  : K   K   R   K
    """
    for op in reversed(history_ops):
        if op['darktable:operation'] not in operations["second_stage"] and op['darktable:operation'] in operations[
            "first_stage"]:
            op.extract()  # remove the op completely
            if verbose:
                print("--removed: ", op['darktable:operation'])
        elif op['darktable:operation'] in operations["overrides"]:
            for key, val in operations["overrides"][op['darktable:operation']].items():
                op[key] = val
        if verbose:
            print("default:    ", op['darktable:operation'], op['darktable:enabled'])
    # set iop_order_version to 5 (for JPEG)
    description = sidecar.find('rdf:Description')
    description['darktable:iop_order_version'] = '5'
    # bring colorin right next to demosaic (early in the stack)
    if description.has_attr("darktable:iop_order_list"):
        description['darktable:iop_order_list'] = description['darktable:iop_order_list'].replace('colorin,0,', '').replace(
            'demosaic,0', 'demosaic,0,colorin,0')
    if _input_xmp.with_suffix('.s2.xmp').is_file():
        _input_xmp.with_suffix('.s2.xmp').unlink()
    _input_xmp.with_suffix('.s2.xmp').touch(exist_ok=False)
    with _input_xmp.with_suffix('.s2.xmp').open('w') as second_stage_xmp_file:
        second_stage_xmp_file.write(sidecar.prettify())

def get_output_path(args, input_path):
    """
    **get_output_path**

    Returns the output path based on the provided arguments and input path.

    This function determines whether to use a custom output path specified in the
    arguments or default to the parent directory of the given input path.

    :param args: Dictionary containing command-line arguments.
    :type args: dict

    :param input_path: The path to an input file or directory.
    :type input_path: pathlib.Path

    :return: The resolved output path as a `pathlib.Path` object.
    :rtype: pathlib.Path
    """
    return pathlib.Path(args["--output-path"]) if args["--output-path"] else input_path.parent

def get_output_extension(args):
    """
    Extracts the file extension from the given arguments.

    :param args:
        A dictionary containing command-line arguments.
        Expected to have a key '--extension' with a string value representing the file extension.

    :type args: dict[str, str]

    :return:
        The file extension, prepended with a period if it doesn't already start with one.

    :rtype: str
    """
    return '.' + args['--extension'] if args['--extension'][0] != '.' else args['--extension']

def get_stage_filepaths(outpath, stage):
    """
    Detailed description of the `get_stage_filepaths` function.

    This function generates file paths for stages based on an output path and a given stage number. The function returns tuples containing the file paths for each specified stage.

    :param outpath:
        :type outpath: Path

            A ``Path`` object representing the base output path for files.

    :param stage:
        :type stage: int

            An integer indicating the stage number (1 or 2).

    :return:
        :rtype: tuple[Path, ...]

            Returns a tuple of ``Path`` objects corresponding to the file paths for the given stage.
    """
    if stage == 1:
        return pathlib.Path(outpath.parent, outpath.stem + '_s1' + '.tif'), \
               pathlib.Path(outpath.parent, outpath.stem + '_s1_denoised' + '.tif')
    elif stage == 2:
        return pathlib.Path(outpath.parent, outpath.stem + '_s2' + '.tif')

def get_command_paths(args):
    """
    Get the paths to external command-line tools.

    This function determines and returns the paths to `darktable-cli` and
    `gmic` based on the provided arguments or default locations depending on
    the operating system.

    :param args: Dictionary containing command-line arguments.
    :type args: dict
    :return: Tuple with the path to darktable-cli and gmic.
    :rtype: tuple

    .. note::

       This function is intended for internal use within the module and should not be
       called directly by users. The default paths are set based on common installation
       directories, but may require customization depending on the user's setup.

    """
    return args["--dt"] if args["--dt"] else (
        "C:/Program Files/darktable/bin/darktable-cli.exe" if os.name == "nt" else "/usr/bin/darktable-cli"), \
           args["--gmic"] if args["--gmic"] else (
        os.path.join(os.path.expanduser("~\\"), "gmic-3.6.1-cli-win64\\gmic.exe") if os.name == "nt" else "/usr/bin/gmic")

def denoise_file(_args: dict, _input_path: pathlib.Path):
    """
    Denoise a file using Darktable and gmic.

    This function processes an image file by denoising it through multiple stages.
    It uses Darktable for initial processing, applies a custom denoising model,
    and optionally deblurs the image with gmic. The function handles various
    configurations and ensures that intermediate files are cleaned up unless
    debug mode is enabled.

    :param _args:
       Dictionary containing command-line arguments and their values.
    :type _args: dict

    :param _input_path:
       Path to the input image file.
    :type _input_path: pathlib.Path

    :return:
       None. The function processes the input file in-place, generating
       a denoised output file.

    :rtype: NoneType

    :raises FileNotFoundError:
       If Darktable is not found or if the input file or its XMP metadata are invalid.
    :raises FileExistsError:
       If there are too many files with the same name already existing.
    :raises ChildProcessError:
       If the subprocess for running Darktable fails.
    :raises RuntimeError:
       If the denoising model does not produce an output file.

    """
    print(_input_path)
    output_dir = get_output_path(_args, _input_path)
    output_extension = get_output_extension(_args)
    outpath = output_dir if output_dir.suffix != '' else (output_dir / _input_path.name).with_suffix(output_extension)
    input_xmp = _input_path.with_suffix(_input_path.suffix + '.xmp')
    sigma = int(_args['--sigma']) if _args.get('--sigma') else 1
    quality = _args['--quality'] if _args.get('--quality') else "90"
    iteration = _args['--iterations'] if _args.get('--iterations') else "10"
    verbose = _args["--verbose"] if _args.get("--verbose") else False

    stage_one_output_filepath, stage_one_denoised_filepath = get_stage_filepaths(outpath, 1)
    stage_two_output_filepath = get_stage_filepaths(outpath, 2)

    config = read_config(verbose=verbose)
    cmd_darktable, cmd_gmic = get_command_paths(_args)

    if not os.path.exists(cmd_gmic) or _args.get("--no_deblur"):
        print("\nWarning: gmic (" + cmd_gmic + ") does not exist or --no_deblur is set, disabled RL-deblur")
        rldeblur = False
        stage_two_output_filepath = outpath  # we won't be running gmic, so no need to use a separate s2 file
    else:
        rldeblur = True

    if not os.path.exists(cmd_darktable):
        print("\nError: darktable-cli (" + cmd_darktable + ") does not exist or not accessible.")
        raise FileNotFoundError

    good_file = check_good_input(_input_path, valid_extensions) or check_good_input(input_xmp, '.xmp')
    if not good_file:
        print("The input raw-image or its XMP were not found, or are not valid.")
        raise FileNotFoundError

    i = 1
    while outpath.exists():
        outpath = outpath.with_stem(outpath.stem + '_' + str(i))
        i += 1
        if i >= 99:
            print("\nError: too many files with the same name already exists. Go look at: ", outpath.parent)
            raise FileExistsError

    parse_darktable_history_stack(input_xmp, config=config, verbose=verbose)

    if os.path.exists(stage_one_output_filepath):
        os.remove(stage_one_output_filepath)

    subprocess.run([cmd_darktable,
                    _input_path,
                    input_xmp.with_suffix('.s1.xmp'),
                    stage_one_output_filepath.name,
                    '--apply-custom-presets', 'false',
                    '--core', '--conf', 'plugins/imageio/format/tiff/bpp=32'
                    ],
                   cwd=outpath.parent, check=True)

    if not os.path.exists(os.path.abspath(stage_one_output_filepath)):
        print("Error: first-stage export not found: ", stage_one_output_filepath)
        raise ChildProcessError

    # ========== call nind-denoise ==========
    # 32-bit TIFF (instead of 16-bit) is needed to retain highlight reconstruction data from stage 1
    # for modified nind-denoise: tif = 16-bit, tiff = 32-bit

    if os.path.exists(stage_one_denoised_filepath):
        os.remove(stage_one_denoised_filepath)

    model_config = config["models"]["nind_generator_650.pt"]
    if not os.path.exists(model_config["path"]):
        from torch import hub
        hub.download_url_to_file(
            "https://f005.backblazeb2.com/file/modelzoo/nind/generator_650.pt", model_config["path"]
        )

    subprocess.run([sys.executable, os.path.abspath("src/nind_denoise/denoise_image.py"),
                    '--network', 'UtNet',
                    '--model_path', model_config["path"],
                    '--input', stage_one_output_filepath,
                    '--output', stage_one_denoised_filepath
                    ],
                   check=True)
    if not os.path.exists(stage_one_denoised_filepath):
        print("Error: Denoiser did not output a file where it was supposed to: ", stage_one_denoised_filepath)
        raise RuntimeError

    clone_exif(_input_path, stage_one_denoised_filepath)

    # ========== invoke darktable-cli with second stage operations==========
    if rldeblur and stage_two_output_filepath.is_file():
        stage_two_output_filepath.unlink()  # delete target of s2 if there is a file there already
    subprocess.run([cmd_darktable,
                    stage_one_denoised_filepath,  # image input
                    input_xmp.with_suffix('.s2.xmp'),  # xmp input
                    stage_two_output_filepath.name,  # image output
                    '--icc-intent', 'PERCEPTUAL', '--icc-type', 'SRGB',
                    '--apply-custom-presets', 'false',
                    '--core', '--conf', 'plugins/imageio/format/tiff/bpp=16'
                    ],
                   cwd=outpath.parent, check=True)

    # call RL-deblur with gmic
    if rldeblur:
        if ' ' in outpath.name:
            # gmic can't handle spaces, so file away the original name for later restoration
            restore_original_outpath = outpath.name
            outpath = outpath.rename(outpath.with_name(outpath.name.replace(' ', '_')))
        else:
            restore_original_outpath = None
        subprocess.run([cmd_gmic, stage_two_output_filepath,
                        '-deblur_richardsonlucy', str(sigma) + ',' + str(iteration) + ',' + '1',
                        '-/', '256', 'cut', '0,255', 'round',
                        '-o', outpath.name + ',' + str(quality)
                         ],
                       cwd=output_dir, check=True)
        if verbose:
            print('Applied RL-deblur to:', outpath)
        if restore_original_outpath is not None:
            outpath.replace(outpath.with_name(restore_original_outpath))  # restore original name with spaces

    clone_exif(stage_one_output_filepath, outpath, verbose=verbose)

    if not _args.get('--debug'):
        for intermediate_file in [stage_one_output_filepath,
                                  stage_two_output_filepath,
                                  input_xmp.with_suffix('.s1.xmp'),
                                  input_xmp.with_suffix('.s2.xmp')]:
            intermediate_file.unlink(missing_ok=True)

if __name__ == '__main__':
    args = docopt(__doc__, version='__version__')
    input_path = pathlib.Path(args["<raw_image>"])
    if input_path.is_dir():
        for file in input_path.iterdir():
            if file.suffix.lower() in valid_extensions:
                print("\n-----------------------", file.name, "-------------------------\n")
                denoise_file(dict(args), _input_path=file)
    else:
        denoise_file(dict(args), _input_path=input_path)
