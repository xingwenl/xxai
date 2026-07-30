import {
  Bell,
  Bot,
  Cable,
  Database,
  FileCode2,
  Monitor,
  Palette,
  Settings,
  Shield,
  Wrench,
  UserCog,
  MessagesSquare,
  AudioWaveform,
  Command,
  GalleryVerticalEnd,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: 'satnaing',
    email: 'satnaingdev@gmail.com',
    avatar: '/avatars/shadcn.jpg',
  },
  teams: [
    {
      name: 'Shadcn Admin',
      logo: Command,
      plan: 'Vite + ShadcnUI',
    },
    {
      name: 'Acme Inc',
      logo: GalleryVerticalEnd,
      plan: 'Enterprise',
    },
    {
      name: 'Acme Corp.',
      logo: AudioWaveform,
      plan: 'Startup',
    },
  ],
  navGroups: [
    {
      title: 'Workspace',
      items: [
        {
          title: 'Chats',
          url: '/chats',
          icon: MessagesSquare,
        },
      ],
    },
    {
      title: 'AI 管理',
      items: [
        {
          title: '智能体管理',
          url: '/ai/bots',
          icon: Bot,
        },
        {
          title: '知识库管理',
          url: '/ai/knowledge-bases',
          icon: Database,
        },
        {
          title: '技能管理',
          url: '/ai/skills',
          icon: FileCode2,
        },
      ],
    },
    {
      title: '系统管理',
      items: [
        {
          title: '人员管理',
          url: '/system/users',
          icon: UserCog,
        },
        {
          title: '角色管理',
          url: '/system/roles',
          icon: Shield,
        },
        {
          title: 'AI HTML 列表',
          url: '/system/ai-html-pages',
          icon: FileCode2,
        },
        {
          title: 'MCP 服务管理',
          url: '/system/mcp-servers',
          icon: Cable,
        },
      ],
    },
    {
      title: 'Preferences',
      items: [
        {
          title: 'Settings',
          icon: Settings,
          items: [
            {
              title: 'Profile',
              url: '/settings',
              icon: UserCog,
            },
            {
              title: 'Account',
              url: '/settings/account',
              icon: Wrench,
            },
            {
              title: 'Appearance',
              url: '/settings/appearance',
              icon: Palette,
            },
            {
              title: 'Notifications',
              url: '/settings/notifications',
              icon: Bell,
            },
            {
              title: 'Display',
              url: '/settings/display',
              icon: Monitor,
            },
          ],
        },
      ],
    },
  ],
}
