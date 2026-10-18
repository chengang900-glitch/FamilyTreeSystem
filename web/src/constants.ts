export const PERSON_TYPES: Record<number, string> = {
  1: '宗男', 2: '宗女', 3: '姻媳', 4: '姻婿', 5: '外孙', 6: '外孙女',
}

export const PC_TYPES: Record<number, string> = {
  1: '亲生', 2: '过继', 3: '收养', 4: '继养', 5: '亲女', 6: '养女', 7: '继女',
}

export const RESOURCE_TYPES: Record<number, string> = {
  1: '谱牒宗册', 2: '传记行述', 3: '凭证契约', 4: '影像照片',
  5: '碑记拓片', 6: '影音记录', 7: '其他',
}

export const EVENT_TYPES: Record<number, string> = {
  1: '家族大事', 2: '祭祀典礼',
}

export function isLiving(p: { death_date?: string | null }): boolean {
  return !p.death_date
}

export function maskPerson(p: any, mask: boolean): any {
  if (!mask || !isLiving(p)) return p
  return { ...p, birth_date: '在世', birth_place: '', record: '（在世者信息已隐藏）', notes: '' }
}
