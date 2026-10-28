from pathlib import Path
p=Path("D:/dsh-fish/test_identity.py")
s=p.read_text(encoding="utf-8")
old='''        self.s.propose_growth("我们在共同游戏中逐渐学会配合。",[2,3],confirmed=True)
        self.assertEqual(self.s.verify()["persona_versions"],ver+1)'''
new='''        ev1=self.s.record("conversation.user","user","我们一起玩游戏吧")
        ev2=self.s.record("conversation.assistant","assistant","好呀，一起玩！")
        self.s.propose_growth("我们在共同游戏中逐渐学会配合。",[ev1,ev2],confirmed=True)
        self.assertEqual(self.s.verify()["persona_versions"],ver+1)'''
if s.count(old)!=1:raise SystemExit("OLD_TEST_ANCHOR_ERROR")
p.write_text(s.replace(old,new),encoding="utf-8")
print("GROWTH_TEST_UPDATED")
