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


  -o <outpath> --output-path=<outpath>  Where to save the result (defaults to current directory)).
  -e <e> --extension=<e>                Output file extension. Supported formats are ....? [default: jpg].
  --dt=<darktable>       Path to darktable-cli. Use this only if not automatically found.
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
import torch.hub
from docopt import docopt
import os, sys, subprocess, shutil
from bs4 import BeautifulSoup
from pathlib import Path
import copy
import exiv2
import yaml
import io

def clone_exif(src_file: str, dst_file: str) -> None:
    """  Convenience function to clone the exif metadata from one image file to another
    """
    src_image = exiv2.ImageFactory.open(src_file)
    src_image.readMetadata()

    dst_image = exiv2.ImageFactory.open(dst_file)
    dst_image.setExifData( src_image.exifData() )
    dst_image.writeMetadata()
    return
"""
  main program, meant to be called manually or by darktable's lua script
"""
if __name__ == '__main__':
    args = docopt(__doc__, version='__version__')
    # @TODO: test and add all available modules, default to keep unlisted ops in 2nd-stage
    with io.open('./src/config/operations.yaml', 'r', encoding='utf-8') as instream:
        var = yaml.safe_load(instream)
        # list of operations to stay in first stage
        first_ops = var["operations"]["first_stage"]
        # list of operations to be moved to second stage
        second_ops = var["operations"]["second_stage"]
        # second stage overrides
        second_overrides = var["overrides"]

    cmd_darktable = args["--dt"] if args["--dt"] else \
        ("C:/Program Files/darktable/bin/darktable-cli.exe" if os.name == "nt" else "/usr/bin/darktable-cli")

    # verify darktable-cli is valid
    if not Path(cmd_darktable).exists():
        print("\nError: darktable-cli (" + cmd_darktable + ") does not exist or not accessible.")
        raise Exception

    # figure out whether to run deblur with gmic
    cmd_gmic = args["--gmic"] if args["--gmic"] else \
        (os.path.join(os.path.expanduser("~\\"),"gmic-3.6.1-cli-win64\\gmic.exe") if os.name == "nt" \
             else "/usr/bin/gmic") #TODO: needs to be fixed to use generic user path
    if not os.path.exists(cmd_gmic) or args["--no_deblur"]:
        print("\nWarning: gmic (" + cmd_gmic+ ") does not exist or --no_deblur is set, disabled RL-deblur")
        rldeblur = False
    else: rldeblur = True

    # define RAW extensions
    valid_extensions = ['3FR','ARW','SR2','SRF','CR2','CR3','CRW','DNG','ERF','FFF','MRW','NEF','NRW','ORF','PEF','RAF','RW2']

    # update the first and second ops for night mode
    if args["--nightmode"]:
        print("\nUpdating ops for nightmode ...")
        nightmode_ops = ['exposure', 'toneequal']
        first_ops.extend(nightmode_ops)

        for op in nightmode_ops:
            second_ops.remove(op)

    # skip invalid/non-existing file
    done = False
    xmp = args["<raw_image>"] + '.xmp'
    # determine a new filename
    basename, input_ext = os.path.splitext(args["<raw_image>"])

    if not os.path.exists(args["<raw_image>"]):
        print("Non-existing file: ", args["<raw_image>"], ", skipping.")
        done = True
    elif not os.path.exists(xmp):
        print("Error: cannot find sidecar file ", xmp)
        done = True
    elif input_ext.lstrip('.').upper() not in valid_extensions:
        print("Non-RAW file: ", args["<raw_image>"], ", skipping.")
        done = True
    if not done:
        i = 0
        ext_out = '.' + args['--extension'] if args['--extension'] else '.jpg'
        out_filename = basename + ext_out
        outpath = os.path.abspath(args["--output-path"]) if args["--output-path"] else os.path.curdir
        while os.path.exists(os.path.join(outpath, out_filename)):
            i = i + 1
            out_filename = basename + '_' + str(i) + ext_out

        with open(xmp, 'r') as f:
            sidecar_xml = f.read()
        sidecar = BeautifulSoup(sidecar_xml, "xml")
        # read the history stack
        history = sidecar.find('darktable:history')
        history_org = copy.copy(history)
        history_ops = history.find_all('rdf:li')
        # sort history ops
        history_ops.sort(key=lambda tag: int(tag['darktable:num']))
        # remove ops not listed in first_ops
        if args["--verbose"]:
            print("\nPrepping first stage ...")
        for op in reversed(history_ops):
            if op['darktable:operation'] not in first_ops:
                # op['darktable:enabled'] = "0"
                op.extract()    # remove the op completely
                if args["--verbose"]:
                    print("--removed: ", op['darktable:operation'])

            else:
                # for "flip": don't remove, only disable
                if op['darktable:operation'] == 'flip':
                    op['darktable:enabled'] = "0"
                    if args["--verbose"]:
                        print("default:    ", op['darktable:operation'])

        with open(basename+'.s1.xmp', 'w') as first_stage:
            first_stage.write(sidecar.prettify())

        # restore the history stack to original
        history.replace_with(history_org)
        history_ops = history_org.find_all('rdf:li')

        # remove ops not listed in second_ops
        # unknown ops NOT in first_ops AND NOT in second_ops, default to keeping them
        # in 1    : N   N   Y   Y
        # in 2    : N   Y   N   Y
        # action  : K   K   R   K

        if args["--verbose"]:
            print("\nPrepping second stage ...")

        for op in reversed(history_ops):
            if op['darktable:operation'] not in second_ops and op['darktable:operation'] in first_ops:
                op.extract()    # remove the op completely
                if args["--verbose"]:
                    print("--removed: ", op['darktable:operation'])
            elif op['darktable:operation'] in second_overrides:
                for key, val in second_overrides[op['darktable:operation']].items():
                    op[key] = val
        if args["--verbose"]:
            print("default:    ", op['darktable:operation'], op['darktable:enabled'])


        # set iop_order_version to 5 (for JPEG)
        description = sidecar.find('rdf:Description')
        description['darktable:iop_order_version'] = '5'

        # bring colorin right next to demosaic (early in the stack)
        if description.has_attr("darktable:iop_order_list"):
            description['darktable:iop_order_list'] = description['darktable:iop_order_list'].replace('colorin,0,', '').replace('demosaic,0', 'demosaic,0,colorin,0')

        with open(basename+'.s2.xmp', 'w') as second_stage:
            second_stage.write(sidecar.prettify())
            #========== invoke darktable-cli with first stage ==========
            # https://github.com/darktable-org/darktable/issues/12958
            # leave the intermediate tiff files in the current folder
            s1_filename = basename + '_s1.tif'
            if os.path.exists(s1_filename):
                os.remove(s1_filename)

        subprocess.run([cmd_darktable,
                        os.path.abspath(args["<raw_image>"]),
                        os.path.abspath(basename+'.s1.xmp'),
                        s1_filename,
                        '--apply-custom-presets', 'false',
                        '--core', '--conf', 'plugins/imageio/format/tiff/bpp=32'
                        ])
        if not os.path.exists(os.path.abspath(s1_filename)):
            print("Error: first-stage export not found: ", s1_filename)
            raise Exception

        #========== call nind-denoise ==========
        # 32-bit TIFF (instead of 16-bit) is needed to retain highlight reconstruction data from stage 1
        # for modified nind-denoise: tif = 16-bit, tiff = 32-bit
        denoised_filename = os.path.abspath(basename + '_s1_denoised.tiff')

        if os.path.exists(denoised_filename):
            os.remove(denoised_filename)
        model_path = os.path.abspath("src/nind_denoise/models/2021-06-14T20_27_nn_train/generator_650.pt")
        # TODO: pytorch.hub is probably the easy-mode path to a simpler inference codebase, w/o moving away from pytorch
        if not os.path.exists(model_path):
            from torch import hub
            hub.download_url_to_file(
                "https://f005.backblazeb2.com/file/modelzoo/nind/generator_650.pt", model_path
            )

        subprocess.run([sys.executable, os.path.abspath("src/nind_denoise/denoise_image.py"),
                        '--network', 'UtNet',
                        '--model_path', model_path,
                        '--input', s1_filename,
                        '--output', denoised_filename
                        ])
        if not os.path.exists(denoised_filename):
            print("Error: denoised image not found: ", denoised_filename)
            raise Exception


        # copy exif from RAW file to denoised image #TODO: one refactor among many needed
        clone_exif(args["<raw_image>"], denoised_filename)
        if args["--verbose"]:
            print('Copied EXIF from ' + args["<raw_image>"] + ' to ' + denoised_filename)


        #========== invoke darktable-cli with second stage ==========
        if rldeblur:
            s2_filename = basename + '_s2.tif'
            if os.path.exists(s2_filename):
                os.remove(s2_filename)
        else:
            s2_filename = out_filename
        subprocess.run([cmd_darktable,
                        denoised_filename,                      # image input
                        os.path.abspath(basename + '.s2.xmp'),  # xmp input
                        s2_filename,                            # image output
                         '--icc-intent', 'PERCEPTUAL', '--icc-type', 'SRGB',
                        '--apply-custom-presets', 'false',
                        '--core', '--conf', 'plugins/imageio/format/tiff/bpp=16'
                        ])

        # call ImageMagick RL-deblur
        if rldeblur:
            tmp_rl_filename = out_filename.replace(' ', '_')  # gmic can't handle spaces
            sigma = args['--sigma'] if args['--sigma'] else 1
            quality = args['--quality'] if args['--quality'] else "90"
            iteration = args['--iterations'] if args['--iterations'] else "10"

            subprocess.run([cmd_gmic, s2_filename,
                            '-deblur_richardsonlucy', str(sigma) + ',' + str(iteration) + ',' + '1',
                            #'-/ 256 cut 0,255 round',
                            '-o', tmp_rl_filename + ',' + str(quality) #
                             ], cwd=outpath)

            # rename tmp file if it's different
            if tmp_rl_filename != out_filename:
                os.rename(tmp_rl_filename, out_filename)
            if args["--verbose"]:
                print('Applied RL-deblur to:', out_filename)

        # copy exif
        clone_exif(s1_filename, out_filename)
        if args["--verbose"]:
            print('Copied EXIF from', s1_filename, 'to', out_filename)

        #========== clean up ==========
        if not args['--debug']:
            os.remove(s1_filename)
            os.remove(denoised_filename)
            os.remove(basename + '.s1.xmp')
            os.remove(basename + '.s2.xmp')

        if (s2_filename != out_filename and os.path.exists(s2_filename)):
            os.remove(s2_filename)

