"""D1 persistence interface. No ORM or database connection pool."""
class DB:
    def __init__(self,binding): self.binding=binding
    def stmt(self,sql,args):
        s=self.binding.prepare(sql)
        return s.bind(*args) if args else s
    async def one(self,sql,*args):
        row=await self.stmt(sql,args).first()
        return native(row)
    async def all(self,sql,*args):
        result=await self.stmt(sql,args).all()
        return native(result.results)
    async def run(self,sql,*args):
        result=await self.stmt(sql,args).run()
        return int(result.meta.changes)
    async def batch(self,items):
        statements=[self.stmt(sql,args) for sql,args in items]
        # The Workers binding unwraps each prepared statement when it converts this list.
        return await self.binding.batch(statements)

def native(x):
    return x.to_py() if hasattr(x,'to_py') else x
