; Refuse replacement/removal of running frozen resources. Opening in append
; mode tests write access without changing bytes; FileExists avoids creation.
!macro MALENIA_CHECK_RESOURCE relative
  ${If} ${FileExists} "$INSTDIR\${relative}"
    ClearErrors
    FileOpen $R8 "$INSTDIR\${relative}" a
    ${If} ${Errors}
      IfSilent +2
      MessageBox MB_OK|MB_ICONSTOP "Close Malenia and its browser bridge, then retry setup. A resource is still in use."
      SetErrorLevel 32
      Quit
    ${EndIf}
    FileClose $R8
  ${EndIf}
!macroend

!macro MALENIA_CHECK_RESOURCES
  Push $R8
  !insertmacro MALENIA_CHECK_RESOURCE "resources\malenia-agent\malenia-agent.exe"
  !insertmacro MALENIA_CHECK_RESOURCE "resources\malenia-native-host\malenia-native-host.exe"
  Pop $R8
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro MALENIA_CHECK_RESOURCES
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro MALENIA_CHECK_RESOURCES
!macroend
