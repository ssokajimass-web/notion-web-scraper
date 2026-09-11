import config
from notion_sync import NotionSync
sync = NotionSync(config.NOTION_API_KEY, config.NOTION_DATABASE_ID)
sync.client.databases.update(database_id=config.NOTION_DATABASE_ID, properties={'サイトURL': {'url': {}}})
print('Done')