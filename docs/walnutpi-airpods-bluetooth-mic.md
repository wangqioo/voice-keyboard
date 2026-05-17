# WalnutPi headless Linux: AirPods/Bluetooth headset microphone investigation

This note records a real debugging session on a WalnutPi running headless Debian Linux. The goal was to use AirPods Pro 3, and potentially other Bluetooth headsets, as the microphone input for `voice-keyboard` on a command-line-only system.

## Environment

- Board: WalnutPi
- OS: Debian GNU/Linux 12 (bookworm), aarch64
- Kernel: Linux 6.1.31
- Bluetooth controller: onboard UART Bluetooth, exposed as `hci0`
- Bluetooth driver stack observed in kernel modules/logs: `sprdbt_tty`, `uwe5622_bsp_sdio`, `hci_uart`
- Headset tested: AirPods Pro 3
- AirPods address used during testing: `34:0E:22:C0:C7:CC`
- Audio stacks tested:
  - PulseAudio + `pulseaudio-module-bluetooth`
  - BlueALSA + `bluez-alsa-utils`

## What worked

Bluetooth pairing, trust, and reconnect worked.

A2DP playback also worked. After switching the card to the A2DP profile, the AirPods could play audio from the WalnutPi.

Useful playback commands:

```bash
vk-airpods-audio
speaker-test -D pulse -t sine -f 440 -l 1
```

A working PulseAudio route used:

```bash
pactl set-card-profile bluez_card.34_0E_22_C0_C7_CC a2dp_sink
pactl set-default-sink bluez_sink.34_0E_22_C0_C7_CC.a2dp_sink
pactl set-sink-mute bluez_sink.34_0E_22_C0_C7_CC.a2dp_sink false
pactl set-sink-volume bluez_sink.34_0E_22_C0_C7_CC.a2dp_sink 50%
```

## What failed

The headset microphone did not produce audio data.

The confusing part: Linux userspace could see a capture device. Both PulseAudio and BlueALSA could expose an HFP/HSP/SCO microphone path, but recording from that device produced empty files or blocked forever.

Example BlueALSA device listing:

```text
bluealsa:SRV=org.bluealsa,DEV=34:0E:22:C0:C7:CC,PROFILE=sco
    34-0E-22-C0-C7-CC, trusted audio-headphones, capture
    SCO (CVSD): S16_LE 1 channel 8000 Hz
```

Example recording command:

```bash
arecord \
  -D bluealsa:SRV=org.bluealsa,DEV=34:0E:22:C0:C7:CC,PROFILE=sco \
  -f S16_LE -c 1 -r 8000 -d 5 -t raw /tmp/bluealsa-sco.raw
```

Result:

- `arecord` opened the device.
- BlueALSA created an SCO transport.
- The raw output file stayed `0 bytes`.
- `arecord` eventually had to be interrupted or timed out.

## Key diagnostic signal

The decisive check was the Bluetooth HCI SCO counter:

```bash
hciconfig -a | sed -n '/RX bytes/,+1p'
```

During repeated microphone recording attempts, the relevant part stayed like this:

```text
RX bytes:... acl:... sco:0 events:... errors:0
TX bytes:... acl:... sco:... commands:... errors:0
```

`acl` changed, but `sco RX` stayed at `0`.

That means Linux never received SCO audio packets from the Bluetooth controller. From the point of view of BlueZ/BlueALSA/PulseAudio, the microphone device may exist, but there are no microphone samples arriving.

## PulseAudio result

PulseAudio exposed an HFP source such as:

```text
bluez_source.34_0E_22_C0_C7_CC.handsfree_head_unit
```

Recording with `parec` produced `0 bytes`:

```bash
parec \
  --device=bluez_source.34_0E_22_C0_C7_CC.handsfree_head_unit \
  --format=s16le --rate=8000 --channels=1 --raw > /tmp/airpods.raw
```

The `voice-keyboard` CLI also blocked when trying to record from the PulseAudio input device.

## BlueALSA result

BlueALSA was configured as an Audio Gateway because the WalnutPi is the computer and the AirPods are the headset:

```ini
# /etc/systemd/system/bluealsa.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/bin/bluealsa -p a2dp-source -p a2dp-sink -p hfp-ag -p hsp-ag --initial-volume=50
```

After restarting BlueALSA, the SCO capture device appeared. BlueALSA logs showed that the HFP Audio Gateway transport started:

```text
New SCO link: 34:0E:22:C0:C7:CC
Starting transport: HFP Audio Gateway (CVSD)
PCM resumed
```

However, recording still produced `0 bytes`, and `hciconfig` still showed `sco RX:0`.

## Firmware configuration experiment

The WalnutPi firmware config contains this field:

```ini
# /lib/firmware/bt_configure_pskey.ini
g_sys_sco_transmit_mode = 0
```

This looked like a possible SCO routing option. The following values were tested:

- `0`
- `1`
- `2`
- `3`

For each value, the test procedure was:

1. Edit `g_sys_sco_transmit_mode`.
2. Restart the WalnutPi Bluetooth service and BlueALSA.
3. Reconnect AirPods.
4. Confirm BlueALSA still exposes SCO capture.
5. Run `arecord` against the SCO capture device.
6. Check output file size and `hciconfig` SCO counters.

All values produced the same result:

- Capture device exists.
- Recording opens the device.
- Output file remains `0 bytes`.
- `sco RX` remains `0`.

The file was restored to the original value after testing:

```ini
g_sys_sco_transmit_mode = 0
```

## Conclusion

AirPods playback works on this WalnutPi. AirPods microphone capture does not work through the onboard Bluetooth controller in this tested system.

The important conclusion is not simply "AirPods are unsupported". The lower-level failure is:

> The onboard WalnutPi Bluetooth controller exposes the HFP/SCO path, but microphone SCO audio packets are not delivered to Linux over HCI.

This is consistent with a known Bluetooth Linux failure mode: some UART Bluetooth modules route SCO audio through a chip-level PCM/I2S interface instead of over HCI. If the board design or vendor driver does not expose that PCM path to Linux audio, BlueZ/BlueALSA can create the profile but cannot receive microphone samples.

A useful external reference is the BlueALSA HFP/HSP documentation, especially the SCO routing discussion:

https://github-wiki-see.page/m/Arkq/bluez-alsa/wiki/Using-BlueALSA-with-HFP-and-HSP-Devices

## Practical recommendation

For `voice-keyboard` on WalnutPi headless Linux, do not depend on the onboard Bluetooth controller for headset microphone input.

Recommended options:

1. Use a USB microphone. This is the fastest and most reliable path for command-line voice input.
2. Use a Linux-compatible USB Bluetooth adapter with working SCO/HFP-over-HCI support, then disable or ignore the onboard Bluetooth controller.
3. Test a non-Apple Bluetooth headset only as a diagnostic. If `sco RX` still stays `0`, the failure is the onboard Bluetooth path, not the headset.

## Reusable diagnostic commands

Check the Bluetooth controller and counters:

```bash
hciconfig -a
hciconfig -a | sed -n '/RX bytes/,+1p'
```

Check Bluetooth pairing state:

```bash
bluetoothctl info 34:0E:22:C0:C7:CC
```

List BlueALSA devices:

```bash
bluealsa-aplay -L
```

Record from BlueALSA SCO capture:

```bash
timeout 8 arecord \
  -D bluealsa:SRV=org.bluealsa,DEV=34:0E:22:C0:C7:CC,PROFILE=sco \
  -f S16_LE -c 1 -r 8000 -d 5 -t raw /tmp/bluealsa-sco.raw
ls -l /tmp/bluealsa-sco.raw
hciconfig -a | sed -n '/RX bytes/,+1p'
```

If the file stays `0 bytes` and `sco RX` remains `0`, userspace audio configuration is not the main issue. The Bluetooth controller/firmware/board audio routing is not delivering microphone SCO packets to Linux.
