import type { Message } from './types'

export class MessageStore {
  private messages: Message[] = []

  constructor(initialMessages: Message[] = []) {
    this.messages = [...initialMessages]
  }

  getMessages(): Message[] {
    return [...this.messages]
  }

  addMessage(message: Message): void {
    this.messages.push(message)
  }

  updateMessage(id: string, updates: Partial<Message>): void {
    const index = this.messages.findIndex((m) => m.id === id)
    if (index !== -1) {
      this.messages[index] = { ...this.messages[index], ...updates }
    }
  }

  removeMessage(id: string): void {
    this.messages = this.messages.filter((m) => m.id !== id)
  }

  clearMessages(): void {
    this.messages = []
  }
}
