import type { Component } from 'vue'

const registeredComponents: Record<string, Component> = {}

export function registerCustomComponent(name: string, component: Component) {
  registeredComponents[name] = component
}

export function getCustomComponent(name?: string) {
  return name ? registeredComponents[name] : undefined
}
