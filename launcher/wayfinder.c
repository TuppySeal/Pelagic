/* Wayfinder.exe: runs `python -m atlasbrowser` inside this process, so Windows (Task Manager, taskbar,
   Alt+Tab) shows "Wayfinder" with its own icon instead of "Python". Lives next to the atlasbrowser package. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <stdio.h>
#include <wchar.h>

typedef int (*PyMainFn)(int, wchar_t **);

static int has_dll(const wchar_t *dir, wchar_t *dll_out, size_t n) {
    WIN32_FIND_DATAW fd;
    wchar_t pattern[MAX_PATH];
    swprintf(pattern, MAX_PATH, L"%ls\\python3??.dll", dir);
    HANDLE h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    swprintf(dll_out, n, L"%ls\\%ls", dir, fd.cFileName);
    FindClose(h);
    return 1;
}

/* Newest Python 3 registered for this user, then for the machine (PEP 514). */
static int from_registry(HKEY root, wchar_t *dir, wchar_t *dll) {
    HKEY core;
    if (RegOpenKeyExW(root, L"Software\\Python\\PythonCore", 0, KEY_READ, &core) != ERROR_SUCCESS) return 0;
    int best = -1;
    wchar_t name[64], path[MAX_PATH];
    for (DWORD i = 0;; i++) {
        DWORD len = 64;
        if (RegEnumKeyExW(core, i, name, &len, NULL, NULL, NULL, NULL) != ERROR_SUCCESS) break;
        int major = 0, minor = 0;
        if (swscanf(name, L"%d.%d", &major, &minor) != 2 || major != 3) continue;
        wchar_t sub[128];
        swprintf(sub, 128, L"%ls\\InstallPath", name);
        DWORD size = sizeof(path);
        if (RegGetValueW(core, sub, NULL, RRF_RT_REG_SZ, NULL, path, &size) != ERROR_SUCCESS) continue;
        PathRemoveBackslashW(path);
        wchar_t d[MAX_PATH];
        if (minor > best && has_dll(path, d, MAX_PATH)) {
            best = minor;
            wcscpy(dir, path);
            wcscpy(dll, d);
        }
    }
    RegCloseKey(core);
    return best >= 0;
}

static int find_python(wchar_t *dir, wchar_t *dll) {
    /* The Python the app was set up with comes first (it has PySide6 installed). */
    if (GetEnvironmentVariableW(L"WAYFINDER_PYTHON", dir, MAX_PATH) && has_dll(dir, dll, MAX_PATH)) return 1;
    if (ExpandEnvironmentStringsW(L"%LOCALAPPDATA%\\Programs\\Python\\Python312", dir, MAX_PATH) &&
        has_dll(dir, dll, MAX_PATH)) return 1;
    return from_registry(HKEY_CURRENT_USER, dir, dll) || from_registry(HKEY_LOCAL_MACHINE, dir, dll);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    wchar_t here[MAX_PATH], pydir[MAX_PATH], pydll[MAX_PATH];
    GetModuleFileNameW(NULL, here, MAX_PATH);
    PathRemoveFileSpecW(here);
    SetCurrentDirectoryW(here);   /* `-m atlasbrowser` imports the package from this folder */

    if (!find_python(pydir, pydll)) {
        MessageBoxW(NULL, L"Wayfinder needs Python 3 with PySide6 installed.\n\n"
                          L"Set WAYFINDER_PYTHON to your Python folder if it is installed somewhere unusual.",
                    L"Wayfinder", MB_ICONERROR);
        return 1;
    }
    SetEnvironmentVariableW(L"PYTHONHOME", pydir);
    SetDllDirectoryW(pydir);
    HMODULE py = LoadLibraryExW(pydll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    PyMainFn py_main = py ? (PyMainFn)GetProcAddress(py, "Py_Main") : NULL;
    if (!py_main) {
        MessageBoxW(NULL, L"Wayfinder couldn't load Python.", L"Wayfinder", MB_ICONERROR);
        return 1;
    }

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    wchar_t **args = (wchar_t **)calloc(argc + 3, sizeof(wchar_t *));
    args[0] = argv[0];
    args[1] = L"-m";
    args[2] = L"atlasbrowser";
    for (int i = 1; i < argc; i++) args[i + 2] = argv[i];
    return py_main(argc + 2, args);
}
