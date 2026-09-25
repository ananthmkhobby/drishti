"use client";

import { useEdgeAutoScroll } from "@/hooks/useEdgeAutoScroll";

// Renders nothing — just activates the edge-of-screen auto-scroll behavior
// for the whole dashboard shell. Split out from ClassroomBrain so the voice
// assistant and the air-mouse scroll behavior stay independent concerns.
export function EdgeAutoScroll() {
  useEdgeAutoScroll();
  return null;
}
