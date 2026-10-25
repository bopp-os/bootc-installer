cmake_minimum_required(VERSION 3.22)
project(tuna-installer-kde VERSION 0.1.0 LANGUAGES CXX)

include(CTest)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Kirigami, Kirigami Addons (FormCard) and the org.kde.desktop Controls style
# are QML-only dependencies: nothing here links against KF6, they are resolved
# at runtime from the QML import path. That keeps the build to plain Qt 6 while
# the UI is fully Plasma-styled.
find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets Qml Quick QuickControls2)

qt_standard_project_setup(REQUIRES 6.5)

# --- org.tunaos.installer.components -----------------------------------------
# SetupModule, the per-step base type. Split into its own QML module for the
# same reason KISS does: modules import it without importing the app.
qt_add_library(tunainstallercomponents STATIC)

qt_add_qml_module(tunainstallercomponents
    URI org.tunaos.installer.components
    VERSION 1.0
    # Distinct on-disk output dirs; two QML modules cannot share one.
    OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/qml/org/tunaos/installer/components
    SOURCES
        src/components/setupmodule.cpp
        src/components/setupmodule.h
)

target_include_directories(tunainstallercomponents PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src/components)
target_link_libraries(tunainstallercomponents PUBLIC Qt6::Quick Qt6::Qml)

# --- org.tunaos.installer -----------------------------------------------------
set(BACKEND_SOURCES
    src/log.cpp
    src/log.h
    src/recipe.cpp
    src/recipe.h
    src/offline.cpp
    src/offline.h
    src/branding.cpp
    src/branding.h
    src/diskmodel.cpp
    src/diskmodel.h
    src/installercontroller.cpp
    src/installercontroller.h
    src/probe.cpp
    src/probe.h
    src/readiness.cpp
    src/readiness.h
    src/validate.cpp
    src/validate.h
)

# copy-defaults.json compiled into branding.cpp as a raw string literal. The
# file is a byte-identical copy of shared/branding/copy-defaults.json.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/copy-defaults.json" TUNA_COPY_DEFAULTS_JSON)
configure_file(src/branding_defaults.h.in "${CMAKE_CURRENT_BINARY_DIR}/branding_defaults.h" @ONLY)
# encryption-choices.json compiled into recipe.cpp the same way: a
# byte-identical copy of fisherman's data/encryption-choices.json.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/encryption-choices.json" TUNA_ENCRYPTION_CHOICES_JSON)
configure_file(src/encryption_choices.h.in "${CMAKE_CURRENT_BINARY_DIR}/encryption_choices.h" @ONLY)

# The whole UI lives in a static library so that both the installer and the
# screenshot harness link the *same* QML module — registering one URI from two
# targets would collide on the generated qmldir.
qt_add_library(tunainstallerapp STATIC)

# Each step lives at modules/<name>/contents/ui/main.qml, the KISS layout, and
# is aliased into the QML module resource as modules/<name>/main.qml so that
# Wizard.qml can resolve it with a plain relative URL.
set(STEP_MODULES welcome disk encryption account confirm progress done)
set(STEP_QML_FILES)
foreach(step ${STEP_MODULES})
    set(src "modules/${step}/contents/ui/main.qml")
    set_source_files_properties(${src} PROPERTIES
        QT_RESOURCE_ALIAS "modules/${step}/main.qml")
    list(APPEND STEP_QML_FILES ${src})
endforeach()

set_source_files_properties(src/qml/Main.qml PROPERTIES QT_RESOURCE_ALIAS Main.qml)
set_source_files_properties(src/qml/Wizard.qml PROPERTIES QT_RESOURCE_ALIAS Wizard.qml)

qt_add_qml_module(tunainstallerapp
    URI org.tunaos.installer
    VERSION 1.0
    OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/qml/org/tunaos/installer
    QML_FILES
        src/qml/Main.qml
        src/qml/Wizard.qml
        ${STEP_QML_FILES}
    SOURCES
        ${BACKEND_SOURCES}
)

target_include_directories(tunainstallerapp PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(tunainstallerapp PUBLIC
    Qt6::Core
    Qt6::Gui
    # QApplication, not QGuiApplication: the org.kde.desktop Controls style
    # paints through QStyle and needs a widgets-capable app object.
    Qt6::Widgets
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
    tunainstallercomponentsplugin
)

qt_add_executable(tuna-installer-kde src/main.cpp)
target_link_libraries(tuna-installer-kde PRIVATE tunainstallerapp tunainstallerappplugin)

# --- screenshot capture -------------------------------------------------------
# Reuses the real QML module — only main.cpp is swapped — so the images
# document the shipped UI rather than a replica.
option(BUILD_CAPTURE "Build the screenshot capture harness" OFF)
if(BUILD_CAPTURE)
    qt_add_executable(tuna-installer-capture tests/capture.cpp)
    target_link_libraries(tuna-installer-capture PRIVATE tunainstallerapp tunainstallerappplugin)
    # The machine the disk step photographs: fisherman's probe answer for a
    # laptop, the fixture every frontend's capture reads.
    target_compile_definitions(tuna-installer-capture PRIVATE
        PROBE_FIXTURE_FILE="${CMAKE_CURRENT_SOURCE_DIR}/../../shared/probe/fixtures/laptop.json"
        # The themed logo shared/walkthrough/capture-branding.json names; see
        # the icon search path in tests/capture.cpp.
        CAPTURE_ICON_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../../data/icons/hicolor/scalable/apps")
endif()

option(BUILD_E2E "Build the end-to-end driver that launches the real backend path" OFF)
if(BUILD_E2E)
    qt_add_executable(tuna-installer-e2e tests/e2e.cpp)
    target_link_libraries(tuna-installer-e2e PRIVATE tunainstallerapp tunainstallerappplugin)
endif()

if(BUILD_TESTING)
    find_package(Qt6 6.5 REQUIRED COMPONENTS Test)

    qt_add_executable(tuna-installer-backend-tests
        tests/test_backend.cpp
        src/log.cpp
        src/recipe.cpp
        src/branding.cpp
        src/offline.cpp
        src/readiness.cpp
        src/probe.cpp
        src/validate.cpp
        src/diskmodel.cpp
        # For the fisherman progress protocol parse. The controller's other
        # halves (QProcess, the recipe file) are not exercised here; the
        # tests below feed appendLine() directly, which is the same entry
        # point readyReadStandardOutput uses.
        src/installercontroller.cpp
    )
    target_include_directories(tuna-installer-backend-tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_BINARY_DIR})
    # The branding fixtures every frontend's resolver is judged by; the test
    # skips when this tree is checked out without the monorepo around it.
    target_compile_definitions(tuna-installer-backend-tests PRIVATE
        BRANDING_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../../shared/branding/fixtures"
        PROBE_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../../shared/probe/fixtures"
        PROGRESS_FIXTURES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../../shared/progress"
        VALIDATE_GOLDENS_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../../fisherman/fisherman/cmd/fisherman/testdata/validate")
    # Qt6::Quick is needed to compile readiness.cpp: armStamp() takes a
    # QQuickWindow, so the type must be complete even though the tests below
    # only exercise writeStamp(), which has no Quick dependency of its own.
    target_link_libraries(tuna-installer-backend-tests PRIVATE Qt6::Core Qt6::Quick Qt6::Test)

    add_test(NAME tuna-installer-backend-tests COMMAND tuna-installer-backend-tests)
endif()

install(TARGETS tuna-installer-kde RUNTIME DESTINATION bin)
install(FILES fisherman-recipe.schema.json DESTINATION share/tuna-installer-kde)

# Desktop entry, AppStream metainfo and icon.
#
# flatpak-builder runs appstreamcli compose over share/metainfo at the end of
# the build; `flatpak build-bundle --oci` then turns its output into the
# org.freedesktop.appstream.* image labels that give software centres an app
# name, icon, licence and description. The icon is not optional here: compose
# drops a desktop-application component that has none.
install(FILES data/org.tunaos.InstallerKde.desktop DESTINATION share/applications)
install(FILES data/org.tunaos.InstallerKde.metainfo.xml DESTINATION share/metainfo)
install(FILES data/icons/hicolor/scalable/apps/org.tunaos.InstallerKde.svg
        DESTINATION share/icons/hicolor/scalable/apps)
