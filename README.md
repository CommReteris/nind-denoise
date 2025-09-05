nind-denoise
==============

A pytorch based image denoising tool for the removal of noise from real photographs. Implements the models developed in    
Benoit Brummer's [NIND Denoise](https://github.com/trougnouf/nind-denoise.git), and the [Darktable](https://github.com/darktable-org/darktable) workflow pioneered by [Huy Hoang](https://github.com/hqhoang).

This fork seeks make their work easier to experiment with and accessible to a wider audience. Notable changes include:
- Support for most hardware via ```torch.accelerator```
  - In addition to cpu-only (universal) and nVidia GPU acceleration, acceleration with Intel XPU(GPU)'s also works.
    - Denoising (on my Intel Xe MAX) is about 6x faster than on cpu, but still slower than using CUDA. (YMMV) 
  - Support for acceleration with AMD GPUs is untested but should work. 
  - I have no way to hash out the details to get this working on MacOS, but it should be 
[possible](https://developer.apple.com/metal/pytorch/)

- Documented installation process on Windows and linux 
  - Installs in a python virtual environment with [uv](https://github.com/astral-sh/uv)
  - Transparently & automatically downloads a pretrained model from a backblaze b2 bucket -> simpler installation

To uninstall, just delete the directory.

# Usage

To denoise an image, run:

```console
$ python3 src/denoise.py "/path/to/photo0123.RAW"
```
**Note:** On windows, if you use forward  _do not_ use single forward slashes for paths. Double is OK:

```powershell 
PS> python3 src\\denoise.py "\bad\path\to\photo0123.RAW"
PS> python3 src\\denoise.py "\\good\\path\\to\\photo0123.RAW"
```

Full usage:

```python
"""
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
```

# Requirements

 - Darktable, and raw images processed with darktable to operate on, along with their .xmp files
 - gmic; on windows go [here](https://gmic.eu/download.html) and scroll down to get the "gmic-cli" version. extract to
 your home directory or be prepared to find the executable and pass its location to denoise.py
 - [variant-enabled](https://astral.sh/blog/wheel-variants) uv
 - The correct gpu drivers for your system are installed along with OpenCL.
 - The oldest linux kernel confirmed working with intel's xpu acceleration is 6.14. So try and get one at least that 
new. 

## Darktable
 - If [this PR](https://github.com/darktable-org/darktable/pull/19189) is still open, you may need to limit yourself to 
version [5.2.1](https://github.com/darktable-org/darktable/releases/tag/release-5.0.1) in order to run rl-deblur.

## Drivers

### nVidia
 - Driver + CUDA

### AMD
 - (Untested as of yet) Possibly just a driver, possibly also ROCm-flavored openCL. Might not actually work. 

### Intel
 - Intel is slightly trickier, with version mismatches between system packages and venv packages causing memory 
alignment issues. Or so it seems. The working strategy is to install the minimum necessary and let uv/pip pull in the 
majority of dependencies inside the venv. Intel has a [guide](https://dgpu-docs.intel.com/driver/client/overview.html)
that details what you need for ubuntu that should give you an idea. Make sure not to overlook the bit that says _"However,
if you plan to use PyTorch, install `libze-dev` and `intel-ocloc` \[as well]"_ On arch linux start with 
 - `intel-compute-runtime`, `level-zero-loader` and `level-zero-headers`

Proper operation can be verified with:
 `clinfo | grep device` and `darktable-cltest`

# Installation:

Warning: this is a prototype developmental codebase. 
The following should be considered developer documentation (or at least for only those willing to experiment); it is not
yet a polished end user install guide.

To install, run the following commands. Good luck.

### 1 - Clone this repo

```console
git clone https://github.com/commreteris/nind-denoise.git
cd nind-denoise
```

### 2 - Create a virtual environment with `uv venv` and activate it.

- The fancy new varient-enabled version of uv makes it possible to _install_ the correct version of PyTorch for your GPU,
  automagically. We'll install that and use it to deploy the rest of the venv.
On **Windows** that would look something like this :

```powershell
PS> powershell -c { $env:INSTALLER_DOWNLOAD_URL = 'https://wheelnext.astral.sh'; irm https://astral.sh/uv/install.ps1 | iex }
PS> uv venv
PS> .venv/Scripts/activate
(nind-denoise) PS> Get-Command python

CommandType   Name          Version    Definition
-----------   ----          -------    ----------
Application   python.exe    3.1x.xx    C:\Users\<user>\...\nind-denoise\.venv/scripts\python.exe

```

From the output of the last command, make sure python.exe is defined inside the .venv directory. Don't proceed until it
is. 


On **Linux**, the following will work for most people. If you are a [fish](https://en.wikipedia.org/wiki/Fish_(Unix_shell)), or
otherwise out of water, go [here](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment) for help. 

 ```bash
 [user@linux]$ curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_DOWNLOAD_URL=https://wheelnext.astral.sh sh
 [user@linux]$ uv venv
 [user@linux]$ source .venv/bin/activate
 [user@linux]$ which python
 /home/user/.../nind-denoise/.venv/bin/python
 [user@linux]$
 
```

From the output of the last command, make sure the python in your path is inside the .venv directory. Don't proceed 
until it is.

## 3 Install required python packages

Installing required packages into your `venv` should be the same for all operating systems, but it may have to be 
tweaked to match your hardware (_i.e.,_ GPU or lack thereof). This command _should_ work for all, but if it doesn't 
just scroll down and pick the right one yourself. 

```console
 $ uv pip install -r requirements.in --upgrade
```

### 4 Verify that PyTorch is picking up your GPU

If you want to make sure you have the expected acceleration provided by your hardware, you can open up a python console
and run some pytorch checks. To get to the python console, just type `python` in the same console as before. If you've
already closed it you'll have to navigate back to the nind-denoise directory and activate the venv again. For example, 
on a Windows machine with an nVidia GPU it might look like this:

```console
(nind-denoise) PS C:\Users\...\nind-denoise> python
Python 3.13.3 (main, Apr  8 2025, 04:04:49) [MSC v.1943 64 bit (AMD64)] on win32
Type "help", "copyright", "credits" or "license" for more information.
>>> import torch
>>> torch.accelerator.is_available()
True
>>> torch.cuda.is_available()
True
>>> torch.xpu.is_available()
False
>>> 
```

Go cite Benoit

```bibtex
@InProceedings{Brummer_2019_CVPR_Workshops,
author = {Brummer, Benoit and De Vleeschouwer, Christophe},
title = {Natural Image Noise Dataset},
booktitle = {Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR) Workshops},
month = {June},
year = {2019}
} 
```
