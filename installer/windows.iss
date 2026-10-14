#ifndef PayloadDir
  #error PayloadDir must refer to the Windows package payload
#endif
#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#ifndef OutputName
  #define OutputName "AutoHarness-Setup"
#endif

[Setup]
AppId={code:GetAppId}
UsePreviousLanguage=no
AppName=AutoHarness for Codex
AppVersion={#AppVersion}
AppPublisher=Arman Khachatryan
AppPublisherURL=https://github.com/arm092/autoharness-codex
DefaultDirName={localappdata}\Programs\AutoHarness for Codex
DefaultGroupName=AutoHarness for Codex
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\plugin\runtime\python.exe
SetupLogging=yes
InfoBeforeFile={#PayloadDir}\INSTALL.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[CustomMessages]
english.CodexTitle=Connect to Codex
english.CodexDescription=Select your installed Codex CLI executable.
english.CodexNote=Codex must already be installed. Python is included in this installer. Close your Codex sessions before updating.
english.ProfileTitle=Codex profile
english.ProfileDescription=Choose the profile where the plugin will be registered.
english.ProfileNote=Keep the default unless you use a custom CODEX_HOME. Updates must use the original profile and installation folder.
english.Finished=Restart Codex, open /hooks and review/trust the five AutoHarness hooks. Your knowledge library is preserved on update and uninstall.
english.RestartCodex=Restart Codex
english.OpenPlugin=Open the AutoHarness plugin page
english.FinishHint=The selected actions run after you click Finish. Codex closes gracefully; if it cannot close, restart it manually. Hook review is available through /hooks in Codex CLI.
english.BadCli=Select a compatible Codex CLI executable. Details:
english.RegistrationFailed=Codex plugin registration failed. Installation cannot be completed. Details:
english.RegistrationHeading=Plugin registration failed
english.RepairNote=Program files were retained for recovery. Correct the error and run Setup again, or uninstall through Windows Apps.
english.UninstallFailed=Could not unregister this plugin safely. Files were retained. Close Codex, restore access to its executable/profile and retry. Details:
russian.CodexTitle=Подключение к Codex
russian.CodexDescription=Выбери исполняемый файл установленного Codex CLI.
russian.CodexNote=Codex уже должен быть установлен. Python встроен в этот установщик. Перед обновлением закрой сессии Codex.
russian.ProfileTitle=Профиль Codex
russian.ProfileDescription=Выбери профиль, в котором будет зарегистрирован плагин.
russian.ProfileNote=Оставь значение по умолчанию, если не используешь свой CODEX_HOME. Для обновления нужны прежние профиль и папка установки.
russian.Finished=Перезапусти Codex, открой /hooks и разреши пять хуков AutoHarness. Библиотека знаний сохраняется при обновлении и удалении.
russian.RestartCodex=Перезапустить Codex
russian.OpenPlugin=Открыть страницу плагина AutoHarness
russian.FinishHint=Действия выполнятся после нажатия «Готово». Codex закроется штатно; если это не получится, перезапусти его вручную. Проверка хуков: /hooks в Codex CLI.
russian.BadCli=Выбери совместимый исполняемый файл Codex CLI. Подробности:
russian.RegistrationFailed=Не удалось зарегистрировать плагин в Codex. Установка не завершена. Подробности:
russian.RegistrationHeading=Плагин не зарегистрирован
russian.RepairNote=Файлы сохранены для восстановления. Исправь ошибку и запусти установщик снова либо удали программу через список приложений Windows.
russian.UninstallFailed=Не удалось безопасно отключить плагин. Файлы сохранены. Закрой Codex, восстанови доступ к его файлу и профилю и повтори удаление. Подробности:

[Files]
Source: "{#PayloadDir}\plugin\runtime\*"; DestDir: "{tmp}\bootstrap\runtime"; Flags: dontcopy
Source: "{#PayloadDir}\plugin\scripts\windows_install.py"; DestDir: "{tmp}\bootstrap"; Flags: dontcopy
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; Subkey: "{code:GetRegistryKey}"; ValueType: string; ValueName: "Codex"; ValueData: "{code:GetCodex}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{code:GetRegistryKey}"; ValueType: string; ValueName: "Profile"; ValueData: "{code:GetProfile}"

[Icons]
Name: "{group}\Installation instructions"; Filename: "{app}\INSTALL.txt"
Name: "{group}\Uninstall AutoHarness"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: files; Name: "{app}\install-state.json"
Type: files; Name: "{app}\install-state.json.new"
Type: files; Name: "{app}\plugin\installation.json"
Type: files; Name: "{app}\finish-result.json"
Type: files; Name: "{app}\plugin\src\autoharness_codex\__pycache__\*.pyc"
Type: dirifempty; Name: "{app}\plugin\src\autoharness_codex\__pycache__"

[Code]
var
  CodexPage: TInputFileWizardPage;
  ProfilePage: TInputDirWizardPage;
  RegistrationFailed: Boolean;
  RegistrationDetail: String;
  RestartCheck, OpenPluginCheck: TNewCheckBox;
  FinishAccepted: Boolean;

function GetAppId(Param: String): String;
begin
  Result := 'AutoHarness-Codex-6F7DF8F8';
  if ExpandConstant('{param:TESTMODE|0}') = '1' then Result := Result + '-Test';
end;

function GetRegistryKey(Param: String): String;
begin
  Result := 'Software\arm092\AutoHarness-Codex';
  if ExpandConstant('{param:TESTMODE|0}') = '1' then Result := Result + '-Test';
end;

function GetCodex(Param: String): String;
begin
  Result := CodexPage.Values[0];
end;

function GetProfile(Param: String): String;
begin
  Result := ProfilePage.Values[0];
end;

procedure InitializeWizard;
var
  Candidate, Profile, Saved: String;
begin
  Profile := GetEnv('CODEX_HOME');
  if Profile = '' then Profile := GetEnv('USERPROFILE') + '\.codex';
  Candidate := GetEnv('AUTOHARNESS_CODEX_BIN');
  if Candidate = '' then Candidate := Profile + '\.sandbox-bin\codex.exe';
  if not FileExists(Candidate) then Candidate := GetEnv('USERPROFILE') + '\.codex\.sandbox-bin\codex.exe';
  if not FileExists(Candidate) then Candidate := FileSearch('codex.exe', GetEnv('PATH'));
  if RegQueryStringValue(HKCU, GetRegistryKey(''), 'Codex', Saved) then Candidate := Saved;
  if RegQueryStringValue(HKCU, GetRegistryKey(''), 'Profile', Saved) then Profile := Saved;
  Candidate := ExpandConstant('{param:CODEX|' + Candidate + '}');
  Profile := ExpandConstant('{param:CODEXHOME|' + Profile + '}');
  CodexPage := CreateInputFilePage(wpSelectDir, CustomMessage('CodexTitle'),
    CustomMessage('CodexDescription'), CustomMessage('CodexNote'));
  CodexPage.Add('Codex CLI:', 'Executable files (*.exe)|*.exe', '.exe');
  CodexPage.Values[0] := Candidate;
  ProfilePage := CreateInputDirPage(CodexPage.ID, CustomMessage('ProfileTitle'),
    CustomMessage('ProfileDescription'), CustomMessage('ProfileNote'), False, '');
  ProfilePage.Add('CODEX_HOME:');
  ProfilePage.Values[0] := Profile;
  RestartCheck := TNewCheckBox.Create(WizardForm);
  RestartCheck.Parent := WizardForm.FinishedPage;
  RestartCheck.SetBounds(WizardForm.FinishedLabel.Left, ScaleY(120), WizardForm.FinishedLabel.Width, ScaleY(22));
  RestartCheck.Caption := CustomMessage('RestartCodex');
  RestartCheck.Checked := True;
  OpenPluginCheck := TNewCheckBox.Create(WizardForm);
  OpenPluginCheck.Parent := WizardForm.FinishedPage;
  OpenPluginCheck.SetBounds(WizardForm.FinishedLabel.Left, ScaleY(146), WizardForm.FinishedLabel.Width, ScaleY(22));
  OpenPluginCheck.Caption := CustomMessage('OpenPlugin');
  OpenPluginCheck.Checked := True;
end;

function Driver(Interpreter, Script, Action, Root, Extra: String; var Detail: String): Boolean;
var
  ResultCode: Integer;
  ReportPath, Parameters: String;
  Report: AnsiString;
begin
  ReportPath := ExpandConstant('{tmp}\registration-result.json');
  DeleteFile(ReportPath);
  Parameters := '"' + Script + '" ' + Action + ' --root "' + Root +
    '" --result "' + ReportPath + '" ' + Extra;
  Result := Exec(Interpreter, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
  if LoadStringFromFile(ReportPath, Report) then Detail := String(Report)
  else Detail := 'Driver exit code: ' + IntToStr(ResultCode);
  Log(Detail);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Detail, Extra: String;
begin
  Result := '';
  ExtractTemporaryFiles('{tmp}\bootstrap\*');
  Extra := '--codex "' + GetCodex('') + '" --codex-home "' + GetProfile('') + '"';
  if not Driver(ExpandConstant('{tmp}\bootstrap\runtime\python.exe'),
    ExpandConstant('{tmp}\bootstrap\windows_install.py'), 'probe', ExpandConstant('{app}'), Extra, Detail) then
    Result := CustomMessage('BadCli') + #13#10 + Detail;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Detail, Extra: String;
begin
  if CurStep = ssPostInstall then begin
    Extra := '--codex "' + GetCodex('') + '" --codex-home "' + GetProfile('') + '"';
    RegistrationFailed := not Driver(ExpandConstant('{app}\plugin\runtime\python.exe'),
      ExpandConstant('{app}\plugin\scripts\windows_install.py'), 'register', ExpandConstant('{app}'), Extra, Detail);
    if RegistrationFailed then begin
      RegistrationDetail := CustomMessage('RegistrationFailed') + #13#10 + Detail + #13#10 + CustomMessage('RepairNote');
      Log('REGISTRATION FAILED: ' + RegistrationDetail);
    end;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    if RegistrationFailed then begin
      WizardForm.FinishedHeadingLabel.Caption := CustomMessage('RegistrationHeading');
      WizardForm.FinishedLabel.Caption := RegistrationDetail;
    end else begin
      WizardForm.FinishedLabel.Caption := CustomMessage('FinishHint');
      WizardForm.FinishedLabel.Height := ScaleY(92);
      RestartCheck.Top := WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height + ScaleY(8);
      OpenPluginCheck.Top := RestartCheck.Top + RestartCheck.Height + ScaleY(4);
      Log('Finish options: restart=' + IntToStr(Ord(RestartCheck.Checked)) + ', plugin=' + IntToStr(Ord(OpenPluginCheck.Checked)));
      Log('Finish layout: labelBottom=' + IntToStr(WizardForm.FinishedLabel.Top + WizardForm.FinishedLabel.Height) + ', restartTop=' + IntToStr(RestartCheck.Top) + ', pluginBottom=' + IntToStr(OpenPluginCheck.Top + OpenPluginCheck.Height) + ', pageHeight=' + IntToStr(WizardForm.FinishedPage.ClientHeight));
    end;
    RestartCheck.Visible := not RegistrationFailed;
    OpenPluginCheck.Visible := not RegistrationFailed;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpFinished then FinishAccepted := not RegistrationFailed;
end;

procedure DeinitializeSetup;
var
  Parameters: String;
  ResultCode: Integer;
begin
  if FinishAccepted and not RegistrationFailed and not WizardSilent then begin
    if RestartCheck.Checked or OpenPluginCheck.Checked then begin
      Parameters := '"' + ExpandConstant('{app}\plugin\scripts\windows_finish.py') + '" --root "' + ExpandConstant('{app}') + '"';
      if RestartCheck.Checked then Parameters := Parameters + ' --restart';
      if OpenPluginCheck.Checked then Parameters := Parameters + ' --open-plugin';
      if not Exec(ExpandConstant('{app}\plugin\runtime\pythonw.exe'), Parameters, '', SW_HIDE, ewNoWait, ResultCode) then
        MsgBox('Could not start the Codex restart helper. Restart Codex manually.', mbError, MB_OK);
    end;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if RegistrationFailed then Result := 1 else Result := 0;
end;

function InitializeUninstall: Boolean;
var
  Detail: String;
begin
  Result := Driver(ExpandConstant('{app}\plugin\runtime\python.exe'),
    ExpandConstant('{app}\plugin\scripts\windows_install.py'), 'check-uninstall', ExpandConstant('{app}'), '', Detail);
  if not Result then MsgBox(CustomMessage('UninstallFailed') + #13#10 + Detail, mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Detail: String;
begin
  if CurUninstallStep = usUninstall then begin
    if not Driver(ExpandConstant('{app}\plugin\runtime\python.exe'),
      ExpandConstant('{app}\plugin\scripts\windows_install.py'), 'unregister', ExpandConstant('{app}'), '', Detail) then
      RaiseException(CustomMessage('UninstallFailed') + #13#10 + Detail);
  end;
end;
