// Runs the shared transition tables (tests/machine-tables.json) against mac/Machines.h, the Mac menu's copy of the
// machines in web/app.js. Build and run (macOS): clang -fobjc-arc -framework Foundation -I mac tests/mac/MachinesTest.m -o t && ./t tests/machine-tables.json
#import <Foundation/Foundation.h>
#import "Machines.h"
static int checks=0,failures=0;
static void eq(id got,id want,NSString *title){
 checks++;
 if(got==want||[got isEqual:want])return;
 failures++;printf("FAIL %s\n  got:  %s\n  want: %s\n",title.UTF8String,[[got description] UTF8String],[[want description] UTF8String]);
}
// A shared table names values by key; resolve them into objects, like resolve() in tests/web_machines.cjs.
static id resolve(NSDictionary *values,id o){
 if([o isKindOfClass:[NSString class]]&&values[o])return values[o];
 if([o isKindOfClass:[NSDictionary class]]){NSMutableDictionary *r=[NSMutableDictionary new];for(NSString *k in o)r[k]=resolve(values,o[k]);return r;}
 return o;
}
static void runTable(NSDictionary *tables,NSString *name,NSDictionary *(^fn)(NSDictionary *,NSDictionary *)){
 NSDictionary *t=tables[name],*values=t[@"values"];
 for(NSArray *row in t[@"rows"]){
  NSDictionary *from=resolve(values,t[@"states"][row[0]]),*ev=resolve(values,t[@"events"][row[1]]),*to=resolve(values,t[@"states"][row[2]]);
  eq(fn(from,ev),to,[NSString stringWithFormat:@"%@ %@ --%@->",name,row[0],row[1]]);
 }
}
static NSDictionary *V(int level,BOOL on){return @{@"level":@(level),@"enabled":@(on)};}
static NSDictionary *Q(NSDictionary *i){return @{@"kind":@"queued",@"intent":i};}
static NSDictionary *dev(NSString *a,BOOL c){return @{@"address":a,@"name":a,@"connected":@(c)};}
int main(int argc,const char *argv[]){@autoreleasepool{
 if(argc<2){printf("usage: MachinesTest tests/machine-tables.json\n");return 2;}
 NSDictionary *tables=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]] options:0 error:nil];
 if(!tables){printf("cannot read %s\n",argv[1]);return 2;}
 NSDictionary *idle=BoseIdle();
 runTable(tables,@"noiser",^NSDictionary *(NSDictionary *s,NSDictionary *e){return BoseNoiser(s,e);});
 runTable(tables,@"intents",^NSDictionary *(NSDictionary *s,NSDictionary *e){return BoseIntents(s,e);});
 for(NSArray *r in tables[@"schedule"][@"rows"]){
  NSDictionary *noise=@{@"kind":r[1],@"queued":V(3,YES)};NSDictionary *intent=@{@"kind":r[2]};
  eq(BoseSchedule([r[0] boolValue],noise,intent,[r[3] boolValue]),r[4],[NSString stringWithFormat:@"schedule change=%@ noise=%@ intent=%@ live=%@",r[0],r[1],r[2],r[3]]);
 }
 NSDictionary *v3=V(3,YES),*v5=V(5,YES);
 // Shown value: newest input, held included, nil when idle.
 NSDictionary *sendingQ=@{@"kind":@"sending",@"sent":v3,@"queued":v5};
 eq(BoseNoiseShown(idle),nil,@"idle shows the verified value");
 eq(BoseNoiseShown(@{@"kind":@"waiting",@"queued":v3}),v3,@"waiting shows the queued value");
 eq(BoseNoiseShown(@{@"kind":@"held",@"queued":v3}),v3,@"held shows its value");
 eq(BoseNoiseShown(@{@"kind":@"sending",@"sent":v3,@"queued":[NSNull null]}),v3,@"sending shows what is sent");
 eq(BoseNoiseShown(sendingQ),v5,@"sending shows the newest input");
 // Intent keys ignore labels and other fields.
 eq(BoseIntentKey(@{@"action":@"connect",@"address":@"BB",@"label":@"x"}),BoseIntentKey(@{@"action":@"connect",@"address":@"BB"}),@"the key ignores labels");
 eq(BoseIntentKey(@{@"action":@"connect",@"address":@"BB",@"replace":@"AA"}),@"connect|BB|AA|",@"key format");
 // Latest wins; the same tap again cancels.
 NSDictionary *q=idle;
 q=BoseIntents(q,@{@"type":@"hold",@"intent":@{@"action":@"disconnect",@"address":@"AA"}});
 q=BoseIntents(q,@{@"type":@"hold",@"intent":@{@"action":@"connect",@"address":@"BB"}});
 q=BoseIntents(q,@{@"type":@"hold",@"intent":@{@"action":@"here"}});
 eq(q,Q(@{@"action":@"here"}),@"latest wins: three taps leave only the last");
 eq(BoseIntents(q,@{@"type":@"hold",@"intent":@{@"action":@"here"}}),idle,@"the same tap again cancels");
 // A noise burst sends the first value at once and only the last afterwards.
 {NSDictionary *s=idle;NSMutableArray *sent=[NSMutableArray new];
  for(int lvl=6;lvl>=3;lvl--){s=BoseNoiser(s,@{@"type":@"input",@"value":V(lvl,YES)});if([s[@"kind"] isEqual:@"waiting"]&&!sent.count){[sent addObject:s[@"queued"][@"level"]];s=BoseNoiser(s,@{@"type":@"send"});}}
  s=BoseNoiser(s,@{@"type":@"ok"});[sent addObject:s[@"queued"][@"level"]];s=BoseNoiser(BoseNoiser(s,@{@"type":@"send"}),@{@"type":@"ok"});
  eq(sent,(@[@6,@3]),@"coalesced burst: 6 then 3");eq(s,idle,@"then idle");}
 // Noise during a change is held, the newest value wins, and it is sent when the change ends.
 {NSDictionary *m=BoseNoiser(idle,@{@"type":@"input",@"value":v3});BOOL change=YES;
  NSString *d=BoseSchedule(change,m,idle,YES);eq(d,@"hold-noise",@"waiting noise is held during a change");m=BoseNoiser(m,@{@"type":@"hold"});
  m=BoseNoiser(m,@{@"type":@"input",@"value":v5});eq(m,(@{@"kind":@"held",@"queued":v5}),@"newest held value wins");
  eq(BoseSchedule(YES,m,idle,YES),@"wait",@"still waiting while the change runs");
  change=NO;eq(BoseSchedule(change,m,idle,YES),@"resume-noise",@"change ended: resume");m=BoseNoiser(m,@{@"type":@"resume"});
  eq(BoseSchedule(change,m,idle,YES),@"noise",@"then send");m=BoseNoiser(m,@{@"type":@"send"});
  eq(m,(@{@"kind":@"sending",@"sent":v5,@"queued":[NSNull null]}),@"the final value is the one sent");}
 // Held, and the change ended with the headset out of reach: dropped, never sent.
 {NSDictionary *m=BoseNoiser(BoseNoiser(idle,@{@"type":@"input",@"value":v3}),@{@"type":@"hold"});
  eq(BoseSchedule(NO,m,idle,NO),@"drop-noise",@"held + unreachable: drop");m=BoseNoiser(m,@{@"type":@"drop"});
  eq(m,idle,@"dropped: idle");eq(BoseNoiseShown(m),nil,@"the display falls back to the verified value");}
 // An intent goes before a waiting noise value, which is then held behind it.
 {NSDictionary *m=BoseNoiser(idle,@{@"type":@"input",@"value":v3}),*i=Q(@{@"action":@"disconnect",@"address":@"AA"});
  eq(BoseSchedule(NO,m,i,YES),@"intent",@"intent first");i=BoseIntents(i,@{@"type":@"release"});
  eq(BoseSchedule(YES,m,i,YES),@"hold-noise",@"noise waits behind the released intent");}
 // A late ok for an older value keeps the newer one.
 {NSDictionary *m=BoseNoiser(BoseNoiser(BoseNoiser(idle,@{@"type":@"input",@"value":v3}),@{@"type":@"send"}),@{@"type":@"input",@"value":v5});
  m=BoseNoiser(m,@{@"type":@"ok"});eq(BoseNoiseShown(m),v5,@"late ok for 3 keeps 5 shown");eq(m[@"kind"],@"waiting",@"and it goes next");}
 // A failure reverts to the verified value, even with a newer one queued.
 eq(BoseNoiser(sendingQ,@{@"type":@"fail"}),idle,@"a failure reverts to the verified value");
 // Release check against the verified snapshot.
 {NSDictionary *two=@{@"devices":@[dev(@"AA",YES),dev(@"BB",YES),dev(@"CC",NO)]},*one=@{@"devices":@[dev(@"AA",YES),dev(@"BB",NO),dev(@"CC",NO)]};
  NSDictionary *discB=@{@"action":@"disconnect",@"address":@"BB"},*discA=@{@"action":@"disconnect",@"address":@"AA"};
  NSDictionary *connB=@{@"action":@"connect",@"address":@"BB"},*connC=@{@"action":@"connect",@"address":@"CC"},*connCrA=@{@"action":@"connect",@"address":@"CC",@"replace":@"AA"};
  eq(BoseReleaseCheck(discA,one,YES)[@"decision"],@"run",@"disconnect of a connected device runs");
  eq(BoseReleaseCheck(discB,one,YES)[@"decision"],@"already-disconnected",@"disconnect of a device no longer connected says so");
  eq(BoseReleaseCheck(connB,two,YES)[@"decision"],@"already-connected",@"connect of a connected device says so");
  eq(BoseReleaseCheck(connC,one,YES)[@"decision"],@"run",@"connect with a free slot runs");
  eq(BoseReleaseCheck(connC,two,YES)[@"decision"],@"busy",@"both slots full and no replace: ask, never guess");
  eq(BoseReleaseCheck(connCrA,two,YES),(@{@"decision":@"run",@"body":connCrA}),@"both slots full and the replace still connected: run it");
  eq(BoseReleaseCheck(connCrA,(@{@"devices":@[dev(@"AA",NO),dev(@"BB",YES),dev(@"CC",NO)]}),YES),(@{@"decision":@"run",@"body":connC}),@"the replace disconnected meanwhile: connect without it");
  eq(BoseReleaseCheck(connCrA,(@{@"devices":@[dev(@"AA",YES),dev(@"BB",YES),dev(@"CC",NO)]}),NO)[@"decision"],@"unreachable",@"headset out of reach: send nothing");
  eq(BoseReleaseCheck(discA,one,NO)[@"decision"],@"unreachable",@"disconnect out of reach: send nothing");
  eq(BoseReleaseCheck(@{@"action":@"connect",@"address":@"ZZ"},one,YES)[@"decision"],@"unreachable",@"unknown device: send nothing");
  eq(BoseReleaseCheck(@{@"action":@"here"},one,NO)[@"decision"],@"run",@"Use on this Mac runs even when the headset is out of reach");}
 printf("mac machines: %d checks, %d failed\n",checks,failures);
 return failures?1:0;
}}
