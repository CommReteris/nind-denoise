--[[
  darktable is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  darktable is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with darktable.  If not, see <http://www.gnu.org/licenses/>.
]]

--[[
  DESCRIPTION
    nind_denoise_rl.lua - NIND-denoise then Richardson-Lucy output sharpening using GMic

    This script provides a new target storage "NIND-denoise RL".
    Images exported will be denoised with NIND-denoise then sharpened with GMic's RL deblur

  REQUIRED SOFTWARE
    NIND-denoise: https://github.com/trougnouf/nind-denoise
    GMic command line interface (CLI) https://gmic.eu/download.shtml
    exiftool to copy EXIF to the final image

  USAGE
    * start the script "nind_denoise_rl" from Script Manager
    * in lua preferences:
      - select the nind_denoise directory (containing src/denoise.py)
      - select GMic cli executable (for RL-deblur)
      - select the exiftool cli executable (optional, to copy EXIF to final image)
    * from "export selected", choose "nind-denoise RL" as target storage
    * for "format options", either TIFF 8-bit or 16-bit is recommended
]]

local dt = require "darktable"
local du = require "lib/dtutils"
local df = require "lib/dtutils.file"
local dtsys = require "lib/dtutils.system"

-- module name
local MODULE_NAME = "nind_denoise_rl"

-- Error codes
local NDERR = {
  CMD_FAILURE = 1001,
  MISSING_BINARY = 1002,
  TEMP_FILE = 1003,
  VAR_SUBSTITUTION = 1004,
  METADATA_FAILURE = 1005  -- Test-visible error code
}

-- check API version
du.check_min_api_version("7.0.0", MODULE_NAME)

-- return data structure for script_manager

local script_data = {}

script_data.destroy = nil -- function to destory the script
script_data.destroy_method = nil -- set to hide for libs since we can't destroy them commpletely yet, otherwise leave as nil
script_data.restart = nil -- how to restart the (lib) script after it's been hidden - i.e. make it visible again

-- OS compatibility
local PS = dt.configuration.running_os == "windows" and  "\\"  or  "/"

-- translation
local gettext = dt.gettext
gettext.bindtextdomain(MODULE_NAME, dt.configuration.config_dir..PS.."lua"..PS.."locale"..PS)
local function _(msgid)
  return gettext.dgettext(MODULE_NAME, msgid)
end

-- initialize conf keys with legacy preference migration
local function migrate_pref(key, type, default)
  -- Check if preference exists by trying to read it and catching errors
  local success, value = pcall(function()
    return dt.preferences.read(MODULE_NAME, key, type)
  end)

  if success then
    return value
  end
  return default
end

local default_dir = dt.configuration.running_os == "windows" and "C:\\nind_denoise" or (os.getenv("HOME") or "") .. "/nind_denoise"

-- Auto-detect gmic executable
local function find_gmic()
  local gmic_paths = {
    "/usr/bin/gmic",
    "/usr/local/bin/gmic",
    "/opt/local/bin/gmic",
    (os.getenv("HOME") or "") .. "/.local/bin/gmic"
  }
  
  for _, path in ipairs(gmic_paths) do
    local f = io.open(path, "r")
    if f then
      f:close()
      return path
    end
  end
  
  -- Try using 'which' command as fallback
  local handle = io.popen("which gmic 2>/dev/null")
  if handle then
    local result = handle:read("*a")
    handle:close()
    if result and result ~= "" then
      return result:gsub("%s+$", "")  -- trim whitespace
    end
  end
  
  return "gmic"  -- fallback to just the command name, hoping it's in PATH
end

local default_gmic = find_gmic()

-- namespace variable
local NDRL = {};

-- Create simple configuration table with values instead of conf_key objects
NDRL.conf = {
  nind_denoise = {value = migrate_pref("nind_denoise", "string", default_dir)},
  output_path = {value = migrate_pref("output_path", "string", "$(FILE_FOLDER)/darktable_exported/$(FILE_NAME)")},
  output_format = {value = migrate_pref("output_format", "integer", 1)},
  sigma = {value = migrate_pref("sigma", "string", "1")},
  iterations = {value = migrate_pref("iterations", "string", "20")},
  jpg_quality = {value = migrate_pref("jpg_quality", "string", "95")},
  rl_deblur_enabled = {value = migrate_pref("rl_deblur_enabled", "bool", false)},
  debug_mode = {value = migrate_pref("debug_mode", "bool", false)},
  import_to_dt = { value = migrate_pref("import_to_dt", "bool", true) }
}

local function output_format_changed()
  if NDRL.output_format == nil then
    return true
  end

  if NDRL.jpg_quality_slider then
    if NDRL.output_format.selected == 1 then
      NDRL.jpg_quality_slider.visible = true
    else
      NDRL.jpg_quality_slider.visible = false
    end
  end

  dt.preferences.write(MODULE_NAME, "output_format", "integer", NDRL.output_format.selected)
end

-- Helper function to check if file exists
local function file_exists(path)
    local f = io.open(path, "r")
    if f then
        f:close()
        return true
    end
    return false
end

-- Forward declaration - will be defined after widgets
local check_environment

NDRL.substitutes = {}
NDRL.placeholders = {"ROLL_NAME","FILE_FOLDER","FILE_NAME","FILE_EXTENSION","ID","VERSION","SEQUENCE","YEAR","MONTH","DAY",
                  "HOUR","MINUTE","SECOND","EXIF_YEAR","EXIF_MONTH","EXIF_DAY","EXIF_HOUR","EXIF_MINUTE","EXIF_SECOND",
                  "STARS","LABELS","MAKER","MODEL","TITLE","CREATOR","PUBLISHER","RIGHTS","USERNAME","PICTURES_FOLDER",
                  "HOME","DESKTOP","EXIF_ISO","EXIF_EXPOSURE","EXIF_EXPOSURE_BIAS","EXIF_APERTURE","EXIF_FOCUS_DISTANCE",
                  "EXIF_FOCAL_LENGTH","LONGITUDE","LATITUDE","ELEVATION","LENS","DESCRIPTION","EXIF_CROP"}

NDRL.output_folder_path = dt.new_widget("entry") {
    tooltip = _("$(ROLL_NAME) - film roll name\n") ..
              _("$(FILE_FOLDER) - image file folder\n") ..
              _("$(FILE_NAME) - image file name\n") ..
              _("$(FILE_EXTENSION) - image file extension\n") ..
              _("$(ID) - image id\n") ..
              _("$(VERSION) - version number\n") ..
              _("$(SEQUENCE) - sequence number of selection\n") ..
              _("$(YEAR) - current year\n") ..
              _("$(MONTH) - current month\n") ..
              _("$(DAY) - current day\n") ..
              _("$(HOUR) - current hour\n") ..
              _("$(MINUTE) - current minute\n") ..
              _("$(SECOND) - current second\n") ..
              _("$(EXIF_YEAR) - EXIF year\n") ..
              _("$(EXIF_MONTH) - EXIF month\n") ..
              _("$(EXIF_DAY) - EXIF day\n") ..
              _("$(EXIF_HOUR) - EXIF hour\n") ..
              _("$(EXIF_MINUTE) - EXIF minute\n") ..
              _("$(EXIF_SECOND) - EXIF seconds\n") ..
              _("$(EXIF_ISO) - EXIF ISO\n") ..
              _("$(EXIF_EXPOSURE) - EXIF exposure\n") ..
              _("$(EXIF_EXPOSURE_BIAS) - EXIF exposure bias\n") ..
              _("$(EXIF_APERTURE) - EXIF aperture\n") ..
              _("$(EXIF_FOCAL_LENGTH) - EXIF focal length\n") ..
              _("$(EXIF_FOCUS_DISTANCE) - EXIF focus distance\n") ..
              _("$(EXIF_CROP) - EXIF crop\n") ..
              _("$(LONGITUDE) - longitude\n") ..
              _("$(LATITUDE) - latitude\n") ..
              _("$(ELEVATION) - elevation\n") ..
              _("$(STARS) - star rating\n") ..
              _("$(LABELS) - color labels\n") ..
              _("$(MAKER) - camera maker\n") ..
              _("$(MODEL) - camera model\n") ..
              _("$(LENS) - lens\n") ..
              _("$(TITLE) - title from metadata\n") ..
              _("$(DESCRIPTION) - description from metadata\n") ..
              _("$(CREATOR) - creator from metadata\n") ..
              _("$(PUBLISHER) - publisher from metadata\n") ..
              _("$(RIGHTS) - rights from metadata\n") ..
              _("$(USERNAME) - username\n") ..
              _("$(PICTURES_FOLDER) - pictures folder\n") ..
              _("$(HOME) - user's home directory\n") ..
              _("$(DESKTOP) - desktop directory"),
    placeholder = _("leave blank to use the location selected below"),
    editable = true,
  }

NDRL.output_folder_selector = dt.new_widget("file_chooser_button") {
    title = _("select output folder"),
    tooltip = _("select output folder"),
    value = NDRL.conf.output_path.value,
    is_directory = true,
    changed_callback = function(self)
      NDRL.conf.output_path.value = self.value
    end
  }

NDRL.output_format = dt.new_widget("combobox") {
    label = _("output format"),
    editable = false,
    selected = 1,
    _("JPG"),
    _("TIFF"),
    changed_callback = function(self)
      NDRL.conf.output_format.value = self.selected
      output_format_changed()
    end
  }

NDRL.jpg_quality_slider = dt.new_widget("slider") {
    label = _("output jpg quality"),
    tooltip = _("Quality of the output JPEG file (70-100)"),
    soft_min = 70,
    soft_max = 100,
    hard_min = 70,
    hard_max = 100,
    step = 2,
    digits = 0,
    value = tonumber(NDRL.conf.jpg_quality.value)
  }

NDRL.rl_deblur_switch = dt.new_widget("check_button") {
    label = _("apply RL deblur"),
    tooltip = _("enable Richardson-Lucy sharpening"),
    value = NDRL.conf.rl_deblur_enabled.value,
    clicked_callback = function(self)
      NDRL.conf.rl_deblur_enabled.value = self.value
    end
  }

NDRL.sigma_slider = dt.new_widget("slider") {
    label = _("sigma"),
    tooltip = _("controls the width of the blur that's applied"),
    soft_min = 0.3,
    soft_max = 2.0,
    hard_min = 0.0,
    hard_max = 3.0,
    step = 0.05,
    digits = 2,
    value = tonumber(NDRL.conf.sigma.value),
    sensitive = NDRL.conf.rl_deblur_enabled.value
  }

NDRL.iterations_slider = dt.new_widget("slider") {
    label = _("iterations"),
    tooltip = _("increase for better sharpening, but slower"),
    soft_min = 0,
    soft_max = 100,
    hard_min = 0,
    hard_max = 100,
    step = 5,
    digits = 0,
    value = tonumber(NDRL.conf.iterations.value),
    sensitive = NDRL.conf.rl_deblur_enabled.value
  }

NDRL.import_to_dt_switch = dt.new_widget("check_button") {
    label = _("Import & stack denoised image"),
    tooltip = _("Automatically import denoised image back into darktable library and group with original"),
    value = NDRL.conf.import_to_dt.value,
    clicked_callback = function(self)
      NDRL.conf.import_to_dt.value = self.value
    end
  }

-- Environment setup button
NDRL.setup_button = dt.new_widget("button") {
    label = _("Setup Python Environment"),
    tooltip = _("Automatically install uv, create venv, and install dependencies"),
    clicked_callback = function(self)
        local denoise_dir = NDRL.conf.nind_denoise.value

        if denoise_dir == "" or denoise_dir == nil then
            dt.print(_("ERROR: Please set nind-denoise directory first"))
            return
        end

        dt.print(_("Starting environment setup..."))
        dt.print(_("Note: First-time setup will download ~2GB of dependencies - this may take 5-10 minutes"))
        self.sensitive = false  -- Disable button during setup

        -- Check if uv is installed (check for file existence instead of command)
        local home = os.getenv("HOME")
        local uv_path = home .. "/.local/bin/uv"
        local uv_exists = file_exists(uv_path)

        if not uv_exists then
            dt.print(_("uv not found - installing..."))
            local install_result = dtsys.external_command("curl -LsSf https://astral.sh/uv/install.sh | sh")

            if install_result ~= 0 then
                dt.print(_("ERROR: Failed to install uv. Please install manually."))
                dt.print(_("Run: curl -LsSf https://astral.sh/uv/install.sh | sh"))
                self.sensitive = true
                return
            end

            dt.print(_("✓ uv installed successfully"))
        else
            dt.print(_("✓ uv already installed"))
        end

        -- Create venv
        dt.print(_("Creating virtual environment..."))
        local venv_cmd = string.format("cd %s && %s venv --clear .venv", df.sanitize_filename(denoise_dir), uv_path)
        local venv_result = dtsys.external_command(venv_cmd)

        if venv_result ~= 0 then
            dt.print(_("ERROR: Failed to create venv"))
            self.sensitive = true
            return
        end
        dt.print(_("✓ Virtual environment created"))

        -- Install dependencies
        dt.print(_("Installing dependencies (this may take a few minutes)..."))
        local install_cmd = string.format("cd %s && %s pip install -e .", df.sanitize_filename(denoise_dir), uv_path)
        local install_result = dtsys.external_command(install_cmd)

        if install_result ~= 0 then
            dt.print(_("ERROR: Failed to install dependencies"))
            self.sensitive = true
            return
        end

        dt.print(_("✓ Dependencies installed successfully"))
        dt.print(_("✓ Setup complete! Python environment is ready."))
        check_environment()  -- Update status indicator
        self.sensitive = true
    end
}

-- Clean environment button
NDRL.clean_button = dt.new_widget("button") {
    label = _("Clean Environment"),
    tooltip = _("Remove venv and build artifacts (for uninstall or fresh setup)"),
    clicked_callback = function(self)
        local denoise_dir = NDRL.conf.nind_denoise.value

        if denoise_dir == "" or denoise_dir == nil then
            dt.print(_("ERROR: Please set nind-denoise directory first"))
            return
        end

        dt.print(_("Cleaning environment..."))
        self.sensitive = false

        -- Remove venv
        local rm_venv = string.format("rm -rf %s/.venv", df.sanitize_filename(denoise_dir))
        os.execute(rm_venv)
        dt.print(_("✓ Removed .venv"))

        -- Remove Python cache and build artifacts
        local rm_cache = string.format("cd %s && find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true", df.sanitize_filename(denoise_dir))
        os.execute(rm_cache)

        local rm_egg = string.format("rm -rf %s/*.egg-info", df.sanitize_filename(denoise_dir))
        os.execute(rm_egg)

        local rm_build = string.format("rm -rf %s/build %s/dist", df.sanitize_filename(denoise_dir), df.sanitize_filename(denoise_dir))
        os.execute(rm_build)

        dt.print(_("✓ Removed build artifacts"))
        dt.print(_("✓ Cleanup complete!"))
        check_environment()  -- Update status indicator
        self.sensitive = true
    end
}

-- Environment status label
NDRL.env_status = dt.new_widget("label") {
    label = _("Environment: Checking...")
}

-- Define check_environment function (was forward declared earlier)
check_environment = function()
    local denoise_dir = NDRL.conf.nind_denoise.value

    if denoise_dir == "" or denoise_dir == nil then
        NDRL.env_status.label = _("Environment: Not configured")
        return false
    end

    -- Check if venv exists by checking for the directory
    local venv_path = denoise_dir .. "/.venv"
    local venv_python = venv_path .. "/bin/python"

    if not file_exists(venv_python) then
        NDRL.env_status.label = _("Environment: ⚠ Not set up")
        return false
    end

    -- Check if torch is installed
    local torch_check = string.format("%s -c 'import torch' 2>/dev/null", venv_python)
    local result = dtsys.external_command(torch_check)

    if result == 0 then
        NDRL.env_status.label = _("Environment: ✓ Ready")
        return true
    else
        NDRL.env_status.label = _("Environment: ⚠ Incomplete")
        return false
    end
end

-- Supported export formats
local function supported(storage, img_format)
  -- only accept TIF for lossless intermediate file.
  -- JPG compression inteferes with denoising
  return (img_format.extension == "tif")
end

-- shamelessly copied the pattern-replacement functions from rename_images.lua
local function build_substitution_list(image, sequence, datetime, username, pic_folder, home, desktop)
    -- build the argument substitution list from each image
    -- local datetime = os.date("*t")
    local colorlabels = {}
    if image.red then table.insert(colorlabels, "red") end
    if image.yellow then table.insert(colorlabels, "yellow") end
    if image.green then table.insert(colorlabels, "green") end
    if image.blue then table.insert(colorlabels, "blue") end
    if image.purple then table.insert(colorlabels, "purple") end
    local labels = #colorlabels == 1 and colorlabels[1] or du.join(colorlabels, ",")
    local eyear,emon,eday,ehour,emin,esec = string.match(image.exif_datetime_taken, "(%d-):(%d-):(%d-) (%d-):(%d-):(%d-)$")
    local replacements = {image.film,
                          image.path,
                          df.get_filename(image.filename),
                          string.upper(df.get_filetype(image.filename)),
                          image.id,image.duplicate_index,
                          string.format("%04d", sequence),
                          datetime.year,
                          string.format("%02d", datetime.month),
                          string.format("%02d", datetime.day),
                          string.format("%02d", datetime.hour),
                          string.format("%02d", datetime.min),
                          string.format("%02d", datetime.sec),
                          eyear,
                          emon,
                          eday,
                          ehour,
                          emin,
                          esec,
                          image.rating,
                          labels,
                          image.exif_maker,
                          image.exif_model,
                          image.title,
                          image.creator,
                          image.publisher,
                          image.rights,
                          username,
                          pic_folder,
                          home,
                          desktop,
                          image.exif_iso,
                          image.exif_exposure,
                          image.exif_exposure_bias,
                          image.exif_aperture,
                          image.exif_focus_distance,
                          image.exif_focal_length,
                          image.longitude,
                          image.latitude,
                          image.elevation,
                          image.exif_lens,
                          image.description,
                          image.exif_crop
                        }

  for i=1,#NDRL.placeholders,1 do
    NDRL.substitutes[NDRL.placeholders[i]] = replacements[i]
  end
end

local function substitute_list(str)
  -- replace the substitution variables in a string
  for match in string.gmatch(str, "%$%(.-%)") do
    local var = string.match(match, "%$%((.-)%)")
    if NDRL.substitutes[var] then
      str = string.gsub(str, "%$%("..var.."%)", NDRL.substitutes[var])
    else
      dt.log_error(string.format("[NDERR-%d] Unrecognized variable substitution: %s", NDERR.VAR_SUBSTITUTION, var))
      return NDERR.VAR_SUBSTITUTION
    end
  end
  return str
end

local function clear_substitute_list()
  for i=1,#NDRL.placeholders,1 do NDRL.substitutes[NDRL.placeholders[i]] = nil end
end

-- Helper function to escape shell arguments
local function escape_shell_arg(arg)
  if dt.configuration.running_os == "windows" then
    -- Windows escaping: wrap in quotes and escape internal quotes
    return '"' .. arg:gsub('"', '""') .. '"'
  else
    -- Unix/Linux escaping: wrap in single quotes and escape single quotes
    return "'" .. arg:gsub("'", "'\\''") .. "'"
  end
end

-- Fallback implementations for df.* functions if they don't exist
local function get_filename(filepath)
  return filepath:match("^.+/(.+)$") or filepath:match("^.+\\(.+)$") or filepath
end

local function get_filetype(filepath)
  return filepath:match("^.+%.(.+)$") or ""
end

local function get_basename(filepath)
  local filename = get_filename(filepath)
  return filename:match("^(.+)%..+$") or filename
end

local function get_path(filepath)
  return filepath:match("^(.+)/[^/]*$") or filepath:match("^(.+)\\[^\\]*$") or "."
end

local function sanitize_filename(filepath)
  -- Basic sanitization - remove or replace problematic characters
  return filepath
end

local function create_unique_filename(filepath)
  if not file_exists(filepath) then
    return filepath
  end
  
  local path = get_path(filepath)
  local basename = get_basename(filepath)
  local ext = get_filetype(filepath)
  
  local counter = 1
  local new_path
  repeat
    new_path = path .. PS .. basename .. "_" .. counter .. "." .. ext
    counter = counter + 1
  until not file_exists(new_path)
  
  return new_path
end

local function mkdir(path)
  if dt.configuration.running_os == "windows" then
    os.execute('mkdir "' .. path .. '" 2>nul')
  else
    os.execute('mkdir -p "' .. path .. '"')
  end
end

local function file_move(src, dest)
  os.rename(src, dest)
end

-- Create fallback df table if functions don't exist
if not df.get_filename then df.get_filename = get_filename end
if not df.get_filetype then df.get_filetype = get_filetype end
if not df.get_basename then df.get_basename = get_basename end
if not df.get_path then df.get_path = get_path end
if not df.sanitize_filename then df.sanitize_filename = sanitize_filename end
if not df.create_unique_filename then df.create_unique_filename = create_unique_filename end
if not df.mkdir then df.mkdir = mkdir end
if not df.file_move then df.file_move = file_move end
if not df.file_exists then df.file_exists = file_exists end

-- Fallback implementations for dtsys.* functions
if not dtsys.escape_shell_arg then
  dtsys.escape_shell_arg = escape_shell_arg
end

if not dtsys.external_command then
  dtsys.external_command = function(cmd)
    return os.execute(cmd)
  end
end

if not dtsys.async_command then
  dtsys.async_command = function(params)
    -- Simple fallback: execute synchronously
    local cmd = params.command
    dt.print_log("Executing command (synchronous fallback): " .. cmd)
    return os.execute(cmd)
  end
end

-- Fallback for dt.log_error if it doesn't exist
if not dt.log_error then
  dt.log_error = function(msg)
    dt.print_log("ERROR: " .. msg)
    dt.print("ERROR: " .. msg)
  end
end

if not dt.log_info then
  dt.log_info = function(msg)
    dt.print_log("INFO: " .. msg)
  end
end

local function store(storage, image, img_format, temp_name, img_num, total, hq, extra)
  local sidecar = image.sidecar
  local to_delete = {}
  table.insert(to_delete, temp_name)

    local new_name

    -- Determine output format
  local file_ext = img_format.extension   -- tiff only

    if not extra.output_format then
    dt.log_error(string.format("[NDERR-%d] Invalid output format configuration", NDERR.CMD_FAILURE))
    return false
  end

    -- Determine output file extension based on format choice
    if extra.output_format == 1 then
        file_ext = "jpg"
    else
        file_ext = "tif"
  end

  -- Determine output path - use same directory as source image by default
  if extra.output_path ~= "" then
    local output_path = extra.output_path
    local datetime = os.date("*t")

    build_substitution_list(image, img_num, datetime, USER, PICTURES, HOME, DESKTOP)
   output_path = substitute_list(output_path)

   if output_path == NDERR.VAR_SUBSTITUTION then
     dt.log_error(string.format("[NDERR-%d] Variable substitution failed", NDERR.VAR_SUBSTITUTION))
     return false
   end

    clear_substitute_list()
    new_name = df.get_path(output_path)..df.get_basename(output_path).."."..file_ext
  else
    -- Default: output to same directory as source image
    new_name = image.path..PS..df.get_basename(temp_name).."."..file_ext
  end

  dt.print_log('new_name: '..new_name)

  -- Error handler for command execution (shared between denoise and RL deblur)
  local function handle_command_error(err)
    dt.log_error(string.format("[NDERR-%d] Command failed: %s", NDERR.CMD_FAILURE, err))
    if NDRL.conf.debug_mode.value then
      dt.log_error(debug.traceback())
    end
    return false
  end

  -- Log processing options for debugging
    dt.print_log("RL deblur enabled: " .. tostring(extra.rl_deblur_enabled))

    -- Always run Python denoise (and optionally RL deblur)
    if extra.denoise_dir == "" or extra.denoise_dir == nil then
        dt.log_error(string.format("[NDERR-%d] nind-denoise directory not configured", NDERR.MISSING_BINARY))
        return false
    end

    local escape_fn = dtsys.escape_shell_arg or escape_shell_arg
    
    -- Step 1: Ensure XMP sidecar exists (create minimal one if needed)
    if not file_exists(sidecar) then
      dt.print(_("Warning: No XMP sidecar found, creating minimal XMP for denoise compatibility"))
      local minimal_xmp = [[<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:darktable="http://darktable.sf.net/"
    darktable:xmp_version="5"
    darktable:raw_params="0"
    darktable:auto_presets_applied="1"
    darktable:history_end="0"
    darktable:iop_order_version="4">
   <darktable:history>
    <rdf:Seq/>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>]]
      
      local xmp_file = io.open(sidecar, "w")
      if xmp_file then
        xmp_file:write(minimal_xmp)
        xmp_file:close()
        dt.print_log("Created minimal XMP at: "..sidecar)
      else
        dt.log_error("Failed to create minimal XMP, denoise may fail")
      end
    end

    -- Step 2: Generate unique filename BEFORE calling Python
    df.mkdir(df.sanitize_filename(df.get_path(new_name)))
    new_name = df.create_unique_filename(new_name)

    -- Step 3: Build denoise.py command - pass full filepath
    local denoise_cmd = extra.nind_denoise.." --tiff-input"..
            " -o " .. escape_fn(new_name) ..
                       " --sidecar "..escape_fn(sidecar)..
                       " --extension "..file_ext..
                       " --quality "..extra.jpg_quality_str
    
    -- Add RL deblur parameters if enabled
    if extra.rl_deblur_enabled then
      denoise_cmd = denoise_cmd.." --sigma="..extra.sigma_str..
                                 " --iterations="..extra.iterations_str
    else
      denoise_cmd = denoise_cmd.." --no_deblur"
    end
    
    -- Add input file
    denoise_cmd = denoise_cmd.." "..escape_fn(temp_name)
    
    dt.print_log("Denoise command: "..denoise_cmd)
    
    local success, result = xpcall(function()
      return dtsys.external_command(denoise_cmd)
    end, handle_command_error)

    if not success or result ~= 0 then
      dt.log_error(_("[NDERR-1001] Denoise/deblur processing failed"))
      return false
    end

    -- Python writes to the exact path we specified
    -- Wait for file to be written
    local retries = 0
    while not file_exists(new_name) and retries < 20 do
      os.execute("sleep 0.2")
      retries = retries + 1
    end

    if not file_exists(new_name) then
        dt.log_error(_("Python output not found: ") .. new_name)
      return false
    end

    dt.print_log("Python output verified at: " .. new_name)
    -- File is already at final destination, no move needed

-- Import to darktable and group with original
  if extra.import_to_dt then
    local success, imported_or_err = pcall(function()
      return dt.database.import(new_name)
    end)
    
    if success then
      local imported_img = imported_or_err
      -- Group with original image
      local group_success, group_err = pcall(function()
        imported_img:group_with(image)
        image:make_group_leader()
      end)
      
      if group_success then
        dt.print(_("Imported and grouped: ")..new_name)
      else
        dt.log_error(_("Import succeeded but grouping failed: ")..tostring(group_err))
      end
    else
      dt.log_error(_("Failed to import to darktable: ")..tostring(imported_or_err))
      -- Don't fail the entire export if import fails
    end
  end

  -- delete temp image
  for i=1,#to_delete,1 do
    os.remove(to_delete[i])
  end

  dt.log_info(_("Successfully exported image: ")..new_name)
end

-- script_manager integration

local function destroy()
  dt.destroy_storage("exp2NDRL")
end

-- UI widgets
local storage_widget = dt.new_widget("box") {
  orientation = "vertical",
  dt.new_widget("section_label") { label = _("Processing Options") },
  NDRL.rl_deblur_switch,
  NDRL.sigma_slider,
  NDRL.iterations_slider,
  dt.new_widget("section_label") { label = _("Output Settings") },
  NDRL.output_folder_path,
  NDRL.output_folder_selector,
  NDRL.output_format,
  NDRL.jpg_quality_slider,
  NDRL.import_to_dt_switch,
  dt.new_widget("section_label") { label = _("Environment Setup") },
  NDRL.env_status,
  NDRL.setup_button,
  NDRL.clean_button,
  dt.new_widget("check_button") {
    label = _("Debug Mode"),
    tooltip = _("Enable verbose logging and stack traces"),
    clicked_callback = function(self)
      NDRL.conf.debug_mode.value = self.value
    end
  }
}

-- Setup export
local function initialize(storage, img_format, image_table, high_quality, extra)
  -- Read preferences (validation removed to prevent initialization failures)
  extra.denoise_dir = dt.preferences.read(MODULE_NAME, "nind_denoise", "string")

  -- Build venv activation command based on OS
  local activate_cmd = ""
  if dt.configuration.running_os == "windows" then
    activate_cmd = "call \"" .. extra.denoise_dir .. "\\.venv\\Scripts\\activate.bat\" && "
  else
    activate_cmd = "source \"" .. extra.denoise_dir .. "/.venv/bin/activate\" && "
  end

  extra.nind_denoise  = activate_cmd .. "python3 \"" .. extra.denoise_dir .. "/src/denoise.py\""
  extra.gmic          = dt.preferences.read(MODULE_NAME, "gmic_exe", "string")
  extra.gmic          = df.sanitize_filename(extra.gmic)
  extra.exiftool      = dt.preferences.read(MODULE_NAME, "exiftool_exe", "string")

  -- Define global variables needed for substitution
  USER = os.getenv("USER") or os.getenv("USERNAME") or "user"
  PICTURES = os.getenv("PICTURES") or os.getenv("HOME") or "."
  HOME = os.getenv("HOME") or "."
  DESKTOP = os.getenv("DESKTOP") or os.getenv("HOME") or "."

  -- determine output path
  extra.output_folder = NDRL.output_folder_selector.value
  extra.output_path   = NDRL.output_folder_path.text
  extra.output_format = NDRL.output_format.selected

  extra.rl_deblur_enabled   = NDRL.conf.rl_deblur_enabled.value
  extra.sigma_str           = string.format("%.0f", NDRL.sigma_slider.value)
  extra.iterations_str      = string.format("%.0f", NDRL.iterations_slider.value)
  extra.jpg_quality_str     = string.format("%.0f", NDRL.jpg_quality_slider.value)
  extra.import_to_dt        = NDRL.conf.import_to_dt.value

  -- save preferences
  -- Preferences now managed through dt.conf observers

end

-- Register storage
dt.register_storage("exp2NDRL", _("nind-denoise RL"), store, nil, supported, initialize, storage_widget)

-- Register preferences
dt.preferences.register(MODULE_NAME, "nind_denoise", "string",
 _ ("nind_denoise directory (NRL)"),
 _ ("directory containing the nind-denoise repository"), "")

dt.preferences.register(MODULE_NAME, "gmic_exe", "file",
 _ ("GMic executable (NRL)"),
 _ ("select executable for GMic command line "), default_gmic)

-- Remove exiftool preference registration

dt.preferences.register(MODULE_NAME, "debug_mode", "bool",
 _ ("Enable debug mode (NRL)"),
 _ ("Enable verbose logging and stack traces"), false)

-- Initialize UI from conf keys
NDRL.output_folder_path.text = NDRL.conf.output_path.value
NDRL.output_format.selected = NDRL.conf.output_format.value
NDRL.jpg_quality_slider.value = tonumber(NDRL.conf.jpg_quality.value)
NDRL.rl_deblur_switch.value = NDRL.conf.rl_deblur_enabled.value
NDRL.sigma_slider.value = tonumber(NDRL.conf.sigma.value)
NDRL.iterations_slider.value = tonumber(NDRL.conf.iterations.value)
NDRL.import_to_dt_switch.value = NDRL.conf.import_to_dt.value
output_format_changed()

-- Check environment health on startup
check_environment()

-- script_manager integration
script_data.destroy = destroy

return script_data

-- vim: shiftwidth=2 expandtab tabstop=2 cindent syntax=lua
-- kate: hl Lua;