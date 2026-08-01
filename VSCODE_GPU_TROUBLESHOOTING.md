# VS Code GPU Rendering Troubleshooting

Use these steps when VS Code typing or rendering hangs with hardware acceleration enabled, especially after a graphics driver update.

Test the steps in order. Before each test, remove this setting from VS Code's `argv.json` if it exists:

```json
"disable-hardware-acceleration": true
```

Close every VS Code window and reopen it after each change.

## 1. Clear the VS Code GPU Cache

VS Code recommends deleting its GPU cache when graphics problems appear after an update.

Close VS Code, open Windows Command Prompt, and run:

```cmd
ren "%APPDATA%\Code\GPUCache" GPUCache.old
```

Reopen VS Code. It will generate a new GPU cache automatically.

Source: [Visual Studio Code FAQ](https://code.visualstudio.com/docs/supporting/faq?cid=vscode-tv)

## 2. Select a Different GPU for VS Code

This applies when the computer has both integrated and dedicated graphics.

1. Open **Windows Settings > System > Display > Graphics**.
2. Add the following application:

   ```text
   %LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe
   ```

3. Select **Options**.
4. Try **High performance** first.
5. Restart VS Code and test it for several minutes.
6. If the problem remains, repeat the test using **Power saving**.

Source: [Microsoft graphics preferences](https://support.microsoft.com/en-us/windows/hardware/display-graphics/optimizations-for-windowed-games-in-windows-11)

## 3. Roll Back the Graphics Driver

If the problem started immediately after a driver update:

1. Open **Device Manager**.
2. Expand **Display adapters**.
3. Right-click the GPU and select **Properties**.
4. Open the **Driver** tab.
5. Select **Roll Back Driver**.
6. Restart Windows.

Source: [Microsoft display driver troubleshooting](https://support.microsoft.com/en-US/Windows/Hardware/Display-Graphics/troubleshoot-screen-flickering-in-windows)

## 4. Reinstall a Stable Graphics Driver

If driver rollback is unavailable:

1. Open **Device Manager**.
2. Expand **Display adapters**.
3. Right-click the GPU and select **Uninstall device**.
4. Restart Windows.
5. Install a stable driver from the laptop or GPU manufacturer's website.

For laptops, the laptop manufacturer's graphics driver may be more stable than the newest generic NVIDIA, AMD, or Intel driver.

Source: [Microsoft driver update and reinstall instructions](https://support.microsoft.com/en-gb/windows/update-drivers-through-device-manager-in-windows-ec62f46c-ff14-c91d-eead-d7126dc1f7b6)

## 5. AMD Integrated Graphics and Windows MPO

Electron applications can stutter on some Windows systems when AMD integrated graphics, hardware acceleration, and Windows Multiplane Overlay (MPO) are used together.

Disabling MPO requires changing the Windows registry. Only investigate this option after confirming that the computer uses affected AMD graphics and after trying the safer steps above.

Source: [Electron issue about AMD graphics and MPO](https://github.com/electron/electron/issues/46206)

## Temporary Workaround

To use VS Code while troubleshooting, start it without GPU acceleration:

```cmd
code --disable-gpu E:\CODES\mini-RAG
```

This disables hardware acceleration only for that VS Code launch.

