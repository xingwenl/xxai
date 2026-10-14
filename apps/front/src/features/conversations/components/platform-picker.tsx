import type { Platform } from '@/api/platform'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/** 平台下拉：会话记录的三层页面共用，放在页头右侧。 */
export function PlatformPicker({
  value,
  platforms,
  onChange,
}: {
  value?: number
  platforms: Platform[]
  onChange: (platformId: number) => void
}) {
  return (
    <Select
      value={value?.toString()}
      onValueChange={(next) => onChange(Number(next))}
    >
      <SelectTrigger className='w-52'>
        <SelectValue placeholder='选择平台' />
      </SelectTrigger>
      <SelectContent>
        {platforms.map((platform) => (
          <SelectItem key={platform.id} value={platform.id.toString()}>
            {platform.name} ({platform.code})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
