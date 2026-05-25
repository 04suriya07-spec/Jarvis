# Dual Boot: Windows 11 + Ubuntu 24.04 LTS
## Step-by-step Guide for Javris OS Setup

---

## BEFORE YOU START — Back Up Windows

Do this first, no exceptions:
- Open **Settings → System → Recovery → Back up your PC**
- Or use an external drive with Windows Backup
- Takes 30–60 minutes but protects everything

---

## PART 1 — Prepare Windows (Do This While on Windows)

### Step 1: Check Your Drive Type
Press `Win + X` → Device Manager → Disk drives  
Note whether you have SSD or HDD (SSD is much better for dual boot).

### Step 2: Shrink Windows Partition
1. Press `Win + X` → **Disk Management**
2. Right-click on `(C:)` → **Shrink Volume**
3. Enter amount to shrink: **`153600`** (= 150 GB for Ubuntu)
   - If you have 512 GB+ SSD, shrink 200 GB
   - If you have 256 GB SSD, shrink 100 GB minimum
4. Click **Shrink**
5. You'll see "Unallocated" space appear — leave it as-is

### Step 3: Disable Fast Startup (Critical)
1. Control Panel → Power Options → **Choose what the power buttons do**
2. Click **"Change settings that are currently unavailable"**
3. Uncheck **"Turn on fast startup"**
4. Save changes

### Step 4: Check BIOS Mode
Press `Win + R` → type `msinfo32` → look for **BIOS Mode**  
- If it says **UEFI** → you're ready (most modern PCs)
- If it says **Legacy** → note this, setup differs slightly

---

## PART 2 — Create Ubuntu USB

### Step 1: Download Ubuntu 24.04 LTS
Download from: `ubuntu.com/download/desktop`  
File: `ubuntu-24.04.x-desktop-amd64.iso` (~5 GB)

### Step 2: Flash USB Drive (8 GB minimum)
Download **Rufus** (free, Windows app): `rufus.ie`

In Rufus:
- Device: your USB drive
- Boot selection: select the Ubuntu .iso
- Partition scheme: **GPT** (if UEFI) or MBR (if Legacy BIOS)
- File system: FAT32
- Click **START** → select **Write in ISO Image mode** if asked

---

## PART 3 — Install Ubuntu

### Step 1: Boot From USB
1. Restart your PC
2. Spam `F12` (or `F2`, `Del`, `Esc` — depends on your PC brand) during boot
   - Dell: `F12`
   - ASUS: `F8` or `Esc`
   - HP: `F9`
   - Lenovo: `F12`
3. Select your USB drive from the boot menu

### Step 2: Try Ubuntu First (Optional but Recommended)
- Select **"Try Ubuntu"** at the first screen
- Make sure WiFi, keyboard, and sound work
- If they do, proceed to install

### Step 3: Install Ubuntu
1. Double-click **"Install Ubuntu 24.04"** on the desktop
2. Language: English (or your preference)
3. **Installation type: select "Install Ubuntu alongside Windows Boot Manager"**
   - This is the safe dual-boot option — does NOT delete Windows
   - If you don't see this option, select "Something else" and manually set the unallocated partition
4. Drag the divider to set Ubuntu's size (use the full unallocated space)
5. Continue → set your timezone, username, password
6. Click **Install Now**
7. Wait 15–25 minutes

### Step 4: First Boot
1. Remove USB when prompted, press Enter
2. **GRUB menu** appears — this is the dual boot selector:
   - `Ubuntu` → boots Ubuntu (your Javris OS)
   - `Windows Boot Manager` → boots Windows normally
3. Default is Ubuntu (5 second countdown)

---

## PART 4 — Set Up Javris on Ubuntu

### Step 1: Connect to WiFi
Click the top-right corner → WiFi icon → connect to your network.

### Step 2: Copy Your Javris Project
Option A — From USB drive:
```bash
cp -r /media/$USER/YourUSB/Javris ~/Javris
```

Option B — From GitHub (if you push it there):
```bash
git clone https://github.com/yourname/Javris.git ~/Javris
```

Option C — Transfer over LAN from Windows:
```bash
# On Windows, share the folder
# On Ubuntu:
scp -r username@windows-ip:/path/to/Javris ~/Javris
```

### Step 3: Run Setup Script
```bash
cd ~/Javris/scripts
chmod +x setup_ubuntu.sh start.sh
./setup_ubuntu.sh
```

This installs everything: Python, audio, Bluetooth, WiFi tools, systemd service, and desktop shortcut.

### Step 4: Add Your API Keys
```bash
nano ~/Javris/.env
```
Fill in at minimum:
- `ANTHROPIC_API_KEY` or `GROQ_API_KEY` (for the AI brain)
- `WEATHER_API_KEY` (optional, for weather skill)

### Step 5: First Run
```bash
cd ~/Javris
python main.py setup      # personalise name, location, tone
python main.py serve --voice   # start everything
```

Open browser at: `http://localhost:8000`

---

## PART 5 — Daily Use

### Switching Between OSes
At boot, GRUB appears for 5 seconds:
- Press `Enter` immediately → Ubuntu (Javris)
- Press `↓` arrow → Windows Boot Manager → Enter → Windows

### Making Ubuntu the Default
If you use Ubuntu 90% of the time, set it as default:
```bash
sudo nano /etc/default/grub
# Change: GRUB_TIMEOUT=10
# Save, then:
sudo update-grub
```

### Starting Javris Automatically
```bash
systemctl --user enable javris
systemctl --user start javris
```
Javris will now start every time you log into Ubuntu.

---

## Things That Just Work on Ubuntu

| Feature | Command Javris Uses |
|---|---|
| WiFi control | `nmcli` |
| Bluetooth | `bluetoothctl` |
| Volume | `pactl` |
| Media (play/pause/next) | `playerctl` |
| Screen brightness | `brightnessctl` |
| Desktop notifications | `notify-send` |
| Screenshots | `pyautogui` |
| Open apps | `gtk-launch` / `xdg-open` |
| Chrome history | `~/.config/google-chrome/Default/History` |

---

## Troubleshooting

**Ubuntu doesn't appear in GRUB / boots straight to Windows:**
- Restart → spam F12 → select Ubuntu from boot menu
- Then: `sudo update-grub`

**WiFi doesn't work on Ubuntu:**
- Most WiFi cards work out of the box on Ubuntu 24.04
- If not: connect via ethernet first, then: `sudo ubuntu-drivers install`

**Audio not working:**
- `sudo apt install pulseaudio` then reboot

**Bluetooth not connecting:**
- Log out and back in after running setup_ubuntu.sh (group permissions)
- Or: `sudo systemctl restart bluetooth`

**Windows won't boot after Ubuntu install:**
- Boot from Ubuntu → `sudo update-grub` → this re-detects Windows

---

## Your Safety Net

- Windows is 100% intact on its own partition
- GRUB is the only new addition to the boot process
- If anything goes wrong: boot Windows normally from GRUB
- Ubuntu can be completely removed by deleting its partition from Windows Disk Management and running `bootrec /fixmbr` from Windows recovery
