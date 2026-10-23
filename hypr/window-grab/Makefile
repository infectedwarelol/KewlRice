PLUGIN_NAME = kewl-window-grab

CXXFLAGS += -shared -fPIC --no-gnu-unique -std=c++2b -Wall -O2
CXXFLAGS += $(shell pkg-config --cflags pixman-1 libdrm hyprland libinput libudev wayland-server xkbcommon)

all: $(PLUGIN_NAME).so

$(PLUGIN_NAME).so: main.cpp
	$(CXX) $(CXXFLAGS) -o $@ main.cpp

install: $(PLUGIN_NAME).so
	install -D -m755 $(PLUGIN_NAME).so $(HOME)/.local/share/hyprland/plugins/$(PLUGIN_NAME).so

clean:
	rm -f $(PLUGIN_NAME).so

.PHONY: all install clean
