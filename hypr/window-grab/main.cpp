#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/version.h>
#include <hyprland/src/desktop/state/ViewState.hpp>
#include <hyprland/src/desktop/state/ViewHitTester.hpp>
#include <hyprland/src/desktop/view/Window.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/layout/LayoutManager.hpp>
#include <hyprland/src/layout/target/Target.hpp>
#include <hyprland/src/managers/eventLoop/EventLoopManager.hpp>
#include <hyprland/src/managers/fullscreen/FullscreenController.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/layout/supplementary/DragController.hpp>

#include <algorithm>
#include <vector>

using Layout::Supplementary::CDragStateController;

template <typename Tag, typename Tag::type Member>
struct SMemberAccess {
    friend typename Tag::type memberOf(Tag) {
        return Member;
    }
};

struct SBeginDragMouse {
    using type = Vector2D CDragStateController::*;
    friend type memberOf(SBeginDragMouse);
};

struct SBeginDragPosition {
    using type = Vector2D CDragStateController::*;
    friend type memberOf(SBeginDragPosition);
};

template struct SMemberAccess<SBeginDragMouse, &CDragStateController::m_beginDragXY>;
template struct SMemberAccess<SBeginDragPosition, &CDragStateController::m_beginDragPositionXY>;

namespace {
    constexpr uint32_t LEFT_BUTTON    = 272;
    constexpr double   TOP_EDGE_SLACK = 2.0;

    HANDLE                           g_handle = nullptr;
    std::vector<CHyprSignalListener> g_listeners;

    struct SGrab {
        PHLWINDOWREF window;
        Vector2D     offset;
        Vector2D     size;
        bool         adjusted = false;
    };

    SGrab g_grab;

    void rememberGrab() {
        g_grab = {};

        const auto MOUSE  = g_pInputManager->getMouseCoordsInternal();
        const auto WINDOW = Desktop::viewState()->hitTest().windowAt(MOUSE, Desktop::View::RESERVED_EXTENTS | Desktop::View::INPUT_EXTENTS | Desktop::View::ALLOW_FLOATING);
        if (!WINDOW || WINDOW->m_isFloating || !WINDOW->layoutTarget())
            return;

        const auto BOX = WINDOW->layoutTarget()->position();
        if (BOX.w < 1 || BOX.h < 1)
            return;

        g_grab.window = WINDOW;
        g_grab.offset = MOUSE - BOX.pos();
        g_grab.size   = BOX.size();
    }

    void keepGrabPoint() {
        if (g_grab.adjusted || !g_layoutManager)
            return;

        auto& controller = g_layoutManager->dragController();
        if (!controller->draggingTiled() || controller->mode() != MBIND_MOVE)
            return;

        const auto TARGET = controller->target();
        const auto WINDOW = g_grab.window.lock();
        if (!TARGET || !WINDOW || TARGET->window() != WINDOW)
            return;

        g_grab.adjusted = true;

        const auto BOX     = TARGET->position();
        const auto ANCHOR  = (*controller).*memberOf(SBeginDragMouse{});
        const auto OFFSETX = std::clamp(g_grab.offset.x * BOX.w / g_grab.size.x, 0.0, BOX.w);
        const auto OFFSETY = std::clamp(g_grab.offset.y, 0.0, BOX.h);
        const auto POS     = Vector2D{ANCHOR.x - OFFSETX, ANCHOR.y - OFFSETY};

        TARGET->setPositionGlobal(CBox{POS, BOX.size()});
        (*controller).*memberOf(SBeginDragPosition{}) = POS;
    }

    void fullscreenIfDroppedOnTop() {
        if (!g_layoutManager)
            return;

        auto& controller = g_layoutManager->dragController();
        if (controller->mode() != MBIND_MOVE)
            return;

        const auto TARGET = controller->target();
        if (!TARGET)
            return;

        const auto WINDOW = TARGET->window();
        if (!WINDOW)
            return;

        const auto MONITOR = WINDOW->m_monitor.lock();
        if (!MONITOR)
            return;

        const auto MOUSE   = g_pInputManager->getMouseCoordsInternal();
        const auto TOPBAND = std::max(MONITOR->m_position.y + TOP_EDGE_SLACK, MONITOR->logicalBoxMinusReserved().y);
        if (MOUSE.y > TOPBAND)
            return;

        g_pEventLoopManager->doLater([weak = PHLWINDOWREF{WINDOW}]() {
            const auto DROPPED = weak.lock();
            if (!DROPPED || !DROPPED->m_isMapped)
                return;
            Fullscreen::controller()->setFullscreenMode(DROPPED, Fullscreen::FSMODE_FULLSCREEN);
        });
    }
}

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    g_handle = handle;

    if (std::string{__hyprland_api_get_hash()} != std::string{__hyprland_api_get_client_hash()}) {
        HyprlandAPI::addNotification(g_handle, "[kewl-window-grab] Version mismatch, rebuild the plugin.", CHyprColor{1.0, 0.2, 0.2, 1.0}, 6000);
        throw std::runtime_error("[kewl-window-grab] version mismatch");
    }

    g_listeners.emplace_back(Event::bus()->m_events.input.mouse.button.listen([](IPointer::SButtonEvent event, Event::SCallbackInfo&) {
        if (event.button != LEFT_BUTTON)
            return;
        if (event.state == WL_POINTER_BUTTON_STATE_PRESSED)
            rememberGrab();
        else
            fullscreenIfDroppedOnTop();
    }));

    g_listeners.emplace_back(Event::bus()->m_events.input.mouse.move.listen([](Vector2D, Event::SCallbackInfo&) { keepGrabPoint(); }));

    return {"kewl-window-grab", "Drag tiled windows by the point you grabbed, drop on the top bar to fullscreen", "infectedware", "1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    g_listeners.clear();
    g_grab = {};
}
