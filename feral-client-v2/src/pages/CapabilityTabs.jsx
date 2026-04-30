import React from "react";
import { NavLink, useParams } from "react-router-dom";

const TAB_ITEMS = [
  { id: "chat", label: "Chat", path: "chat", end: true },
  { id: "voice", label: "Voice", path: "voice", end: true },
  { id: "vision", label: "Vision", path: "vision", end: true },
  { id: "peripherals", label: "Peripherals", path: "peripherals", end: true },
  { id: "apps", label: "Apps", path: "apps", end: false },
  { id: "settings", label: "Settings", path: "settings", end: true },
];

export default function CapabilityTabs({ deviceId: explicitDeviceId }) {
  const { device_id: routeDeviceId } = useParams();
  const deviceId = explicitDeviceId || routeDeviceId || "";
  const basePath = `/pair/${encodeURIComponent(deviceId)}`;

  return (
    <nav aria-label="Phone capability tabs" data-testid="pair-capability-tabs">
      <div className="v2-tabs v2-tabs--md" role="tablist">
        {TAB_ITEMS.map((item) => (
          <NavLink
            key={item.id}
            to={`${basePath}/${item.path}`}
            end={item.end}
            role="tab"
            data-testid={`pair-tab-${item.id}`}
            className={({ isActive }) => `v2-tab${isActive ? " is-active" : ""}`}
          >
            <span className="v2-tab-label">{item.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
