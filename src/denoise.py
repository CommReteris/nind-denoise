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
import subprocess
import sys
import pathlib

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

def check_good_input(path: pathlib.Path, extensions = None) -> bool:
    """ Checks that the given path is a good, raw image file.

    :param path:
    :type path:
    :param extensions:
    :type extensions:
    :return:
    :rtype:
    """
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

def clone_exif(src_file: pathlib.Path, dst_file: pathlib.Path,verbose=False) -> None:
    """Convenience function to clone the exif metadata from one image file to another

    :param src_file:
    :type src_file:
    :param dst_file:
    :type dst_file:
    :return:
    :rtype:
    """
    src_image = exiv2.ImageFactory.open(str(src_file))
    src_image.readMetadata()

    dst_image = exiv2.ImageFactory.open(str(dst_file))
    dst_image.setExifData( src_image.exifData() )
    dst_image.writeMetadata()
    if verbose:
        print('Copied EXIF from', src_file, 'to', dst_file)

def read_config(config_path ='./src/config/operations.yaml', _nightmode = False, verbose=False) -> dict:
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
        if op['darktable:operation'] not in operations["second_stage"] and op['darktable:operation'] in operations["first_stage"]:
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
        description['darktable:iop_order_list'] = description['darktable:iop_order_list'].replace('colorin,0,',
                                                                                                  '').replace(
            'demosaic,0', 'demosaic,0,colorin,0')
    if _input_xmp.with_suffix('.s2.xmp').is_file():
        _input_xmp.with_suffix('.s2.xmp').unlink()
    _input_xmp.with_suffix('.s2.xmp').touch(exist_ok=False)
    with _input_xmp.with_suffix('.s2.xmp').open('w') as second_stage_xmp_file:
        second_stage_xmp_file.write(sidecar.prettify())

def denoise_file(_args: dict, _input_path: pathlib.Path):
    """Main denoising function

    :param _args:
    :type _args:
    :param _input_path:
    :type _input_path:
    """
    print(_input_path)
    output_dir = pathlib.Path(_args["--output-path"]) if _args["--output-path"] else _input_path.parent
    output_extension = '.' + _args['--extension'] if _args['--extension'][0] != '.' else _args['extension']
    outpath = output_dir if output_dir.suffix != '' else (output_dir / _input_path.name).with_suffix(
        output_extension)
    input_xmp = _input_path.with_suffix(_input_path.suffix + '.xmp')
    sigma = _args['--sigma'] if _args['--sigma'] else 1
    quality = _args['--quality'] if _args['--quality'] else "90"
    iteration = _args['--iterations'] if _args['--iterations'] else "10"
    verbose = args["--verbose"] if _args["--verbose"] else False
    stage_one_output_filepath = pathlib.Path(
        outpath.parent,
        outpath.stem + '_s1' + '.tif'
    )
    stage_one_denoised_filepath = pathlib.Path(
        outpath.parent,
        outpath.stem + '_s1_denoised' + '.tif'
    )
    stage_two_output_filepath = pathlib.Path(
        outpath.parent,
        outpath.stem + '_s2' + '.tif'
    )
    config = read_config(verbose=verbose)
    cmd_darktable = _args["--dt"] if _args["--dt"] else \
        ("C:/Program Files/darktable/bin/darktable-cli.exe" if os.name == "nt" else "/usr/bin/darktable-cli")
    cmd_gmic = _args["--gmic"] if _args["--gmic"] else \
        (os.path.join(os.path.expanduser("~\\"), "gmic-3.6.1-cli-win64\\gmic.exe") if os.name == "nt" \
             else "/usr/bin/gmic")
    # figure out whether to run deblur with gmic
    if not os.path.exists(cmd_gmic) or _args["--no_deblur"]:
        print("\nWarning: gmic (" + cmd_gmic + ") does not exist or --no_deblur is set, disabled RL-deblur")
        rldeblur = False
        stage_two_output_filepath = outpath # we won't be running gmic, so no need to use a seperate s2 file
    else:
        rldeblur = True

    # Checks
    # check for darktable-cli
    if not os.path.exists(cmd_darktable):
        print("\nError: darktable-cli (" + cmd_darktable + ") does not exist or not accessible.")
        raise FileNotFoundError

    # skip invalid/non-existing file
    good_file = check_good_input(_input_path, valid_extensions) or check_good_input(input_xmp, '.xmp')
    if not good_file:
        print("The input raw-image or its XMP were not found, or are not valid.")
        raise FileNotFoundError

    i = 1
    while outpath.exists():
        outpath = outpath.with_stem(outpath.stem + '_' + str(i))
        i = i + 1
        if i >= 99:
            print("\nError: too many files with the same name already exists. Go look at: ", outpath.parent)
            raise FileExistsError

    parse_darktable_history_stack(input_xmp, config=config, verbose=verbose)

    #========== invoke darktable-cli with first stage ==========
    # https://github.com/darktable-org/darktable/issues/12958
    # leave the intermediate tiff files in the current folder
        
    if os.path.exists(stage_one_output_filepath):
        os.remove(stage_one_output_filepath)

    subprocess.run([cmd_darktable,
                    _input_path,
                    input_xmp.with_suffix('.s1.xmp'),
                    stage_one_output_filepath.name,
                    '--apply-custom-presets', 'false',
                    '--core', '--conf', 'plugins/imageio/format/tiff/bpp=32'
                    ], 
                   cwd=outpath.parent,check=True)

    if not os.path.exists(os.path.abspath(stage_one_output_filepath)):
        print("Error: first-stage export not found: ", stage_one_output_filepath)
        raise ChildProcessError

    #========== call nind-denoise ==========
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

    #========== invoke darktable-cli with second stage operations==========
    if rldeblur and stage_two_output_filepath.is_file():
        stage_two_output_filepath.unlink() # delete target of s2 if there is a file there already
    subprocess.run([cmd_darktable,
                    stage_one_denoised_filepath,                      # image input
                    input_xmp.with_suffix('.s2.xmp'),  # xmp input
                    stage_two_output_filepath.name,                            # image output
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
                        '-o', outpath.name + ',' + str(quality) #
                         ],
                       cwd=output_dir, check=True)
        if verbose:
            print('Applied RL-deblur to:', outpath)
        if restore_original_outpath is not None:
            outpath.replace(outpath.with_name(restore_original_outpath))  # restore original name with spaces

    clone_exif(stage_one_output_filepath, outpath, verbose=verbose)

    #========== clean up ==========
    if not _args['--debug']:
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
