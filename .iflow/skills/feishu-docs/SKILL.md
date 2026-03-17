---
name: feishu-docs
description: Operate Feishu (Lark) cloud documents including cloud drive, wiki, documents, spreadsheets, and bitables. Use this skill whenever the user mentions 飞书, Feishu, Lark, 云文档, 知识库, 电子表格, 多维表格, or wants to create/edit/manage any Feishu document, even if they don't explicitly mention the platform name. Also trigger when the user asks about publishing articles, writing documentation, or managing data in a collaborative workspace.
---

# 飞书云文档操作 Skill

让 AI 助手能够操作飞书云文档，包括云空间、知识库、文档、电子表格和多维表格。

## 环境配置

需要在 `.env` 文件中配置以下环境变量：

```bash
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=xxxx
```

## 权限要求

在飞书开放平台创建应用后，需要开通以下权限：

| 模块 | 权限 |
|------|------|
| 云文档 | `docx:document`, `docx:document:readonly` |
| 电子表格 | `sheets:spreadsheet`, `sheets:spreadsheet:readonly` |
| 多维表格 | `bitable:app`, `bitable:app:readonly` |
| 云空间 | `drive:drive`, `drive:drive:readonly` |
| 知识库 | `wiki:wiki`, `wiki:wiki:readonly` |

## API 端点

基础 URL: `https://open.feishu.cn/open-apis`

## 快速开始

### Python 工具函数

```python
import os
import requests

FEISHU_APP_ID = os.environ.get('FEISHU_APP_ID')
FEISHU_APP_SECRET = os.environ.get('FEISHU_APP_SECRET')
API_BASE = 'https://open.feishu.cn/open-apis'

def get_token():
    """获取 tenant_access_token"""
    resp = requests.post(f'{API_BASE}/auth/v3/tenant_access_token/internal', json={
        'app_id': FEISHU_APP_ID,
        'app_secret': FEISHU_APP_SECRET
    })
    return resp.json()['tenant_access_token']

def api_call(method, path, data=None, token=None):
    """通用 API 调用"""
    if token is None:
        token = get_token()
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'{API_BASE}{path}'
    if method == 'GET':
        return requests.get(url, headers=headers).json()
    elif method == 'POST':
        return requests.post(url, json=data, headers=headers).json()
    elif method == 'PUT':
        return requests.put(url, json=data, headers=headers).json()
    elif method == 'DELETE':
        return requests.delete(url, headers=headers).json()
```

## 一、云文档 (Docx)

### 创建文档

```python
def create_document(title, folder_token=None):
    data = {'document': {'title': title}}
    if folder_token:
        data['document']['folder_token'] = folder_token
    result = api_call('POST', '/docx/v1/documents', data)
    return result['data']['document']

# 返回: {'document_id': 'doxcnxxx', 'title': '标题'}
```

### 添加内容块

**block_type 类型（重要：16 分割线不支持！）:**

| 值 | 类型 | 字段名 | 备注 |
|----|------|--------|------|
| 2 | 文本 | text | 普通段落 |
| 3 | 标题1 | heading1 | 一级标题 |
| 4 | 标题2 | heading2 | 二级标题 |
| 5 | 标题3 | heading3 | 三级标题 |
| 12 | 无序列表 | bullet | - 开头的列表 |
| 13 | 有序列表 | ordered | 1. 开头的列表 |
| 14 | 代码块 | code | 代码块 |
| 15 | 引用 | quote | > 开头的引用 |
| ~~16~~ | ~~分割线~~ | ~~divider~~ | ❌ **不支持！会报错 99992402** |

> ⚠️ **关键提示**: `block_type: 16` (分割线) 在 API 中不被支持，使用时会返回错误码 `99992402`。
> 解决方案：使用文本块显示分割线，如 `{'block_type': 2, 'text': {'elements': [{'text_run': {'content': '──────────────'}}]}}`

### 完整的 Markdown 转文档块函数

```python
import re

def parse_markdown_to_blocks(md_text):
    """将 Markdown 转换为飞书文档块列表
    
    支持的特性：
    - 标题 (h1-h4)
    - 无序列表 (- 或 *)
    - 有序列表 (1. 2. 3.)
    - 代码块 (```)
    - 引用 (>)
    - 分割线 (---) -> 转为文本行
    - 表格 -> 转为文本行
    """
    blocks = []
    lines = md_text.split('\n')
    in_code_block = False
    code_content = []
    in_table = False
    table_rows = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # 代码块处理
        if line.strip().startswith('```'):
            if in_code_block:
                code_text = '\n'.join(code_content)
                blocks.append({
                    'block_type': 14,
                    'code': {
                        'elements': [{'text_run': {'content': code_text}}],
                        'style': {'language': 1}
                    }
                })
                code_content = []
                in_code_block = False
            else:
                in_code_block = True
            i += 1
            continue
        
        if in_code_block:
            code_content.append(line)
            i += 1
            continue
        
        # 表格处理
        if '|' in line and line.strip().startswith('|'):
            if not in_table:
                in_table = True
                table_rows = []
            if re.match(r'^\|[\s\-:|]+\|$', line.strip()):
                i += 1
                continue
            cells = [c.strip() for c in line.strip().split('|')[1:-1]]
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            table_text = '\n'.join([' | '.join(row) for row in table_rows])
            blocks.append({
                'block_type': 2,
                'text': {'elements': [{'text_run': {'content': table_text}}]}
            })
            in_table = False
            table_rows = []
            continue
        
        line = line.rstrip()
        if not line.strip():
            i += 1
            continue
        
        # 标题
        if line.startswith('# '):
            blocks.append({'block_type': 3, 'heading1': {'elements': [{'text_run': {'content': line[2:].strip()}}]}})
        elif line.startswith('## '):
            blocks.append({'block_type': 4, 'heading2': {'elements': [{'text_run': {'content': line[3:].strip()}}]}})
        elif line.startswith('### '):
            blocks.append({'block_type': 5, 'heading3': {'elements': [{'text_run': {'content': line[4:].strip()}}]}})
        elif line.startswith('#### '):
            blocks.append({'block_type': 5, 'heading3': {'elements': [{'text_run': {'content': line[5:].strip()}}]}})
        # 列表
        elif line.startswith('- ') or line.startswith('* '):
            blocks.append({'block_type': 12, 'bullet': {'elements': [{'text_run': {'content': line[2:].strip()}}]}})
        elif re.match(r'^\d+\.\s', line):
            content = re.sub(r'^\d+\.\s', '', line).strip()
            blocks.append({'block_type': 13, 'ordered': {'elements': [{'text_run': {'content': content}}]}})
        # 分割线 -> 转为文本
        elif line.strip() == '---':
            blocks.append({'block_type': 2, 'text': {'elements': [{'text_run': {'content': '─────────────────────────'}}]}})
        # 引用
        elif line.startswith('> '):
            blocks.append({'block_type': 15, 'quote': {'elements': [{'text_run': {'content': line[2:].strip()}}]}})
        # 普通文本
        else:
            blocks.append({'block_type': 2, 'text': {'elements': [{'text_run': {'content': line}}]}})
        
        i += 1
    
    return blocks
```

### 分批写入内容块

飞书 API 每次最多写入 50 个块，长文档需要分批写入：

```python
def write_blocks_to_document(doc_id, blocks, batch_size=50):
    """分批写入内容块到文档"""
    total = len(blocks)
    for start in range(0, total, batch_size):
        batch = blocks[start:start + batch_size]
        resp = api_call('POST', f'/docx/v1/documents/{doc_id}/blocks/{doc_id}/children', 
                       {'children': batch})
        if resp.get('code') != 0:
            print(f"警告: 第 {start//batch_size + 1} 批写入失败: {resp}")
        else:
            print(f"✓ 第 {start//batch_size + 1} 批写入成功 ({len(batch)} 个块)")
```

## 二、知识库 (Wiki)

### 知识库权限配置（关键！）

**仅有 API 权限不够，还需要将机器人添加到知识库！**

1. 创建群聊并添加机器人
2. 知识库设置 → 成员设置 → 添加管理员 → 选择群聊

### 获取知识空间列表

```python
def list_wiki_spaces():
    """获取知识空间列表"""
    return api_call('GET', '/wiki/v2/spaces?page_size=20')

# 返回格式（注意：不在 'space' 键下）:
# {'code': 0, 'data': {'items': [{'name': 'iflow', 'space_id': '7617055129014897861', ...}]}}
```

### 获取知识空间节点

```python
def list_wiki_nodes(space_id):
    """获取知识空间节点列表"""
    return api_call('GET', f'/wiki/v2/spaces/{space_id}/nodes?page_size=50')
```

### 移动云文档到知识库

```python
def move_doc_to_wiki(space_id, doc_token, obj_type='docx'):
    """移动云空间文档到知识库"""
    return api_call('POST', f'/wiki/v2/spaces/{space_id}/nodes/move_docs_to_wiki',
                   {'obj_token': doc_token, 'obj_type': obj_type})
```

### 更新知识库节点标题

```python
def update_wiki_node_title(space_id, node_token, title):
    """更新知识库节点的显示标题"""
    return api_call('POST', f'/wiki/v2/spaces/{space_id}/nodes/{node_token}/update_title', {'title': title})
```

## 三、常见问题与踩坑记录

### 1. block_type 16 分割线报错

**错误**: `{'code': 99992402, 'field_violations': [{'field': 'children[*].block_type', 'value': '16'}]}`

**原因**: 飞书 API 不支持 block_type 16（分割线）

**解决方案**: 使用文本块代替
```python
# 错误
{'block_type': 16, 'divider': {}}
# 正确
{'block_type': 2, 'text': {'elements': [{'text_run': {'content': '──────────────'}}]}}
```

### 2. 知识库列表返回空

**原因**: 机器人没有被添加为知识库管理员

**解决方案**: 通过群聊间接授权机器人知识库管理员权限

### 3. 知识库 API 返回格式

```python
# 错误
item['space']['name']  # KeyError!

# 正确
item['name']
item['space_id']
```

### 4. 内容写入失败但文档已创建

**场景**: 写入内容块时出错，但文档已经创建，导致知识库中出现空文档

**解决方案**: 
1. 在写入前验证所有块格式正确
2. 如需重新发布，需手动删除空文档

## 四、常见错误码

| 错误码 | 说明 | 解决方案 |
|--------|------|---------|
| 1770001 | 参数无效 | 检查请求参数格式 |
| 1770032 | 权限不足 | 检查应用权限配置和文档权限 |
| 1770002 | 资源不存在 | 检查 ID 是否正确 |
| 99992402 | 字段验证失败 | 检查 block_type 是否支持（16 不支持） |

## 五、参考资源

- [飞书开放平台文档](https://open.feishu.cn/document)
- [官方 Lark MCP](https://github.com/larksuite/lark-openapi-mcp)
