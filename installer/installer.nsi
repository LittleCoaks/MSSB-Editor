; MSSB Editor installer (NSIS). Built by `python build.py --installer` after the
; PyInstaller one-folder build; expects dist\MSSB Editor\ under the repo root.
;   makensis /DVERSION=x.y.z installer\installer.nsi
Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APPNAME "MSSB Editor"
!define PUBLISHER "LittleCoaks"
!define REGKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MSSBEditor"

Name "${APPNAME}"
OutFile "..\dist\MSSB Editor Setup ${VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define MUI_ICON "..\zzzzdat\ui\icon.ico"
!define MUI_UNICON "..\zzzzdat\ui\icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\MSSB Editor.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "MSSB Editor" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  ; a previous version's bundle is removed first so renamed files do not pile up
  RMDir /r "$INSTDIR\_internal"
  File /r "..\dist\MSSB Editor\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKLM "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "${REGKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKLM "${REGKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${REGKEY}" "Publisher" "${PUBLISHER}"
  WriteRegStr HKLM "${REGKEY}" "DisplayIcon" "$INSTDIR\MSSB Editor.exe"
  WriteRegStr HKLM "${REGKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${REGKEY}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKLM "${REGKEY}" "QuietUninstallString" "$\"$INSTDIR\Uninstall.exe$\" /S"
  WriteRegDWORD HKLM "${REGKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${REGKEY}" "NoRepair" 1
  ; installed size for Programs and Features
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${REGKEY}" "EstimatedSize" "$0"
SectionEnd

Section "Start menu shortcut" SecStart
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\MSSB Editor.exe" "" "$INSTDIR\MSSB Editor.exe" 0
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\MSSB Editor.exe" "" "$INSTDIR\MSSB Editor.exe" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "The program. Settings and cache live in %APPDATA%\${APPNAME}; exports go to Documents\${APPNAME}."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStart} "A Start menu entry."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "A shortcut on the desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "${APPNAME} needs 64-bit Windows."
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  ; the program only: %APPDATA%\MSSB Editor (settings, cache) and Documents\MSSB Editor (exports) are kept
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\MSSB Editor.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
  DeleteRegKey HKLM "${REGKEY}"
  DeleteRegKey HKLM "Software\${APPNAME}"
SectionEnd
