import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function AssociationToolbar({
  keyword,
  onKeywordChange,
  status,
  onStatusChange,
}: {
  keyword: string
  onKeywordChange: (value: string) => void
  status: string
  onStatusChange: (value: string) => void
}) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      <Input
        value={keyword}
        onChange={(event) => onKeywordChange(event.target.value)}
        placeholder='搜索名称或标识'
        className='w-56'
      />
      <Select value={status} onValueChange={onStatusChange}>
        <SelectTrigger className='w-36'>
          <SelectValue placeholder='全部状态' />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value='all'>全部</SelectItem>
          <SelectItem value='bound'>已关联</SelectItem>
          <SelectItem value='unbound'>未关联</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}
