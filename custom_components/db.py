
from sqlalchemy import create_engine, text
import threading


import logging
_LOGGER = logging.getLogger(__name__)

class TimescaleDBConnection:
	def __init__(self, host, port, user, password, database):
		self.host = host
		self.port = port
		self.user = user
		self.password = password
		self.database = database
		self.engine = None
		self.lock = threading.Lock()

	async def connect(self):
		# SQLAlchemy engine (sync, thread-safe)
		url = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
		self.engine = create_engine(url, future=True)

	async def close(self):
		if self.engine:
			self.engine.dispose()
			self.engine = None

	async def fetch(self, query, **params):
		import asyncio
		loop = asyncio.get_running_loop()
		return await loop.run_in_executor(None, self._fetch_sync, query, dict(params))

	def _fetch_sync(self, query, params):
		# Debug: log params type en inhoud
		_LOGGER.debug(f"_fetch_sync params type: {type(params)}, value: {params}")
		if not isinstance(params, dict):
			params = dict(params)
		with self.lock:
			with self.engine.connect() as conn:
				# Pass params via the parameters keyword argument
				stmt = text(query)
				result = conn.execute(stmt, parameters=params)
				return [dict(row._mapping) for row in result]
