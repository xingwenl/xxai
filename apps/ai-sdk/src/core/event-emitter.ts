type EventHandler = (...args: any[]) => void

export class EventEmitter {
  private events: Map<string, EventHandler[]> = new Map()

  on(event: string, handler: EventHandler): void {
    if (!this.events.has(event)) {
      this.events.set(event, [])
    }
    this.events.get(event)!.push(handler)
  }

  off(event: string, handler: EventHandler): void {
    const handlers = this.events.get(event)
    if (!handlers) return
    this.events.set(
      event,
      handlers.filter((h) => h !== handler)
    )
  }

  emit(event: string, ...args: any[]): void {
    const handlers = this.events.get(event)
    if (!handlers) return
    handlers.forEach((handler) => {
      try {
        handler(...args)
      } catch (e) {
        console.error(`Error in event handler for ${event}:`, e)
      }
    })
  }

  removeAllListeners(event?: string): void {
    if (event) {
      this.events.delete(event)
    } else {
      this.events.clear()
    }
  }
}
