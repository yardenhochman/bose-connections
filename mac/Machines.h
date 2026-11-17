// Pure state machines of the menu-bar app: a port of the "machines" block in web/app.js (docs/state-machines.md 5, 6b).
// Foundation only, no UI framework and no state: every function takes values and returns a value.
// tests/mac/MachinesTest.m runs the shared tables (tests/machine-tables.json) against them.
#import <Foundation/Foundation.h>
static inline NSDictionary *BoseIdle(void){return @{@"kind":@"idle"};}
static inline NSString *BoseText(NSDictionary *d,NSString *key){id v=d[key];return [v isKindOfClass:[NSString class]]?v:@"";}
static inline id BoseValue(NSDictionary *d,NSString *key){id v=d[key];return v==[NSNull null]?nil:v;}
// Noise writer: idle | waiting{queued} | held{queued} (a change runs) | sending{sent,queued}. The newest input is the one sent next.
static inline NSDictionary *BoseNoiser(NSDictionary *s,NSDictionary *e){
 NSString *kind=s[@"kind"],*type=e[@"type"];
 if([type isEqual:@"input"]){
  if([kind isEqual:@"sending"])return @{@"kind":@"sending",@"sent":s[@"sent"],@"queued":e[@"value"]};
  return @{@"kind":[kind isEqual:@"held"]?@"held":@"waiting",@"queued":e[@"value"]};
 }
 if([type isEqual:@"hold"])return [kind isEqual:@"waiting"]?@{@"kind":@"held",@"queued":s[@"queued"]}:s;
 if([type isEqual:@"resume"])return [kind isEqual:@"held"]?@{@"kind":@"waiting",@"queued":s[@"queued"]}:s;
 if([type isEqual:@"drop"])return [kind isEqual:@"held"]?BoseIdle():s;
 if([type isEqual:@"send"])return [kind isEqual:@"waiting"]?@{@"kind":@"sending",@"sent":s[@"queued"],@"queued":[NSNull null]}:s;
 if([type isEqual:@"ok"]){
  if(![kind isEqual:@"sending"])return s;
  id queued=BoseValue(s,@"queued");return queued?@{@"kind":@"waiting",@"queued":queued}:BoseIdle();
 }
 if([type isEqual:@"fail"])return BoseIdle();
 return s;
}
// The newest noise input, or nil when idle (then the verified headset value shows).
static inline NSDictionary *BoseNoiseShown(NSDictionary *s){
 if([s[@"kind"] isEqual:@"idle"])return nil;
 return BoseValue(s,@"queued")?:s[@"sent"];
}
// Intent queue: idle | queued{intent}. Latest wins; the same intent again cancels it. An intent is {action, address, replace}.
static inline NSString *BoseIntentKey(NSDictionary *i){
 if(!i)return @"";
 return [@[BoseText(i,@"action"),BoseText(i,@"address"),BoseText(i,@"replace"),BoseText(i,@"target")] componentsJoinedByString:@"|"];
}
static inline NSDictionary *BoseIntents(NSDictionary *s,NSDictionary *e){
 NSString *type=e[@"type"];
 if([type isEqual:@"hold"])return [s[@"kind"] isEqual:@"queued"]&&[BoseIntentKey(s[@"intent"]) isEqual:BoseIntentKey(e[@"intent"])]?BoseIdle():@{@"kind":@"queued",@"intent":e[@"intent"]};
 if([type isEqual:@"cancel"]||[type isEqual:@"release"])return BoseIdle();
 return s;
}
// What runs next, one request toward the controller at a time. Returns wait | hold-noise | intent | resume-noise | drop-noise | noise | idle.
static inline NSString *BoseSchedule(BOOL change,NSDictionary *noise,NSDictionary *intent,BOOL live){
 NSString *n=noise[@"kind"];
 if(change)return [n isEqual:@"waiting"]?@"hold-noise":@"wait";
 if([n isEqual:@"sending"])return @"wait";
 if([intent[@"kind"] isEqual:@"queued"])return @"intent";
 if([n isEqual:@"held"])return live?@"resume-noise":@"drop-noise";
 if([n isEqual:@"waiting"])return @"noise";
 return @"idle";
}
// A released intent checked against the verified snapshot. Returns {decision, body}: decision is run (send body) |
// already-disconnected | already-connected | busy (both slots full, no replace: ask, never guess) | unreachable.
static inline NSDictionary *BoseReleaseCheck(NSDictionary *intent,NSDictionary *snapshot,BOOL live){
 NSString *action=intent[@"action"];
 if([action isEqual:@"here"])return @{@"decision":@"run",@"body":intent};
 NSDictionary *device=nil,*replaceDevice=nil;NSUInteger connected=0;NSString *replace=BoseText(intent,@"replace");
 for(NSDictionary *d in [snapshot[@"devices"] isKindOfClass:[NSArray class]]?snapshot[@"devices"]:@[]){
  if([d[@"address"] isEqual:intent[@"address"]])device=d;
  if(replace.length&&[d[@"address"] isEqual:replace])replaceDevice=d;
  if([d[@"connected"] boolValue])connected++;
 }
 if(!device||!live)return @{@"decision":@"unreachable"};
 if([action isEqual:@"disconnect"])return [device[@"connected"] boolValue]?@{@"decision":@"run",@"body":@{@"action":@"disconnect",@"address":intent[@"address"]}}:@{@"decision":@"already-disconnected"};
 if([device[@"connected"] boolValue])return @{@"decision":@"already-connected"};
 BOOL keep=replaceDevice&&[replaceDevice[@"connected"] boolValue];
 if(connected>=2&&!keep)return @{@"decision":@"busy"};
 return @{@"decision":@"run",@"body":keep?@{@"action":@"connect",@"address":intent[@"address"],@"replace":replace}:@{@"action":@"connect",@"address":intent[@"address"]}};
}
