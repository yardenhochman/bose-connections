#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <CoreBluetooth/CoreBluetooth.h>
#import "Machines.h"
static NSString *const BoseURL=@"http://127.0.0.1:8847/",*const BosePopoverURL=@"http://127.0.0.1:8847/?view=popover";
// Texts of tests/switch-contract.json (checked verbatim by tests/test_mac_contract.py).
static NSString *const BosePending=@"Connecting…",*const BoseReplacing=@"Replacing {label}…",*const BoseOk=@"Playing on Bose 700",*const BoseBusy=@"Both slots busy · choose one to replace",*const BoseReplace=@"Replace {label}",*const BoseRetryHint=@" · tap to retry";
// Texts of the input rule shared with web/app.js (docs/state-machines.md 5, 6b).
static NSString *const BoseNoiseDropped=@"Noise change not sent: the headphones aren’t reachable now";
static NSString *const BoseErrUnreachable=@"Couldn’t reach the headphones",*const BoseErrTimeout=@"Took too long to switch",*const BoseErrUnverified=@"The headphones didn’t confirm the switch",*const BoseErrKeepOne=@"Can’t replace that one: keep a phone, PC or Mac connected",*const BoseErrNoAudio=@"Connected, but no sound from the headphones",*const BoseErrAudioNotMoved=@"Headphones connected, but PC audio didn’t switch",*const BoseErrForgotten=@"The headphones forgot this PC · hold their Bluetooth button until “Ready to connect”";
@interface WeakScript : NSObject <WKScriptMessageHandler>
@property (weak) id<WKScriptMessageHandler> target;
@end
@implementation WeakScript
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {[self.target userContentController:controller didReceiveScriptMessage:message];}
@end
@interface App : NSObject <NSApplicationDelegate,CBCentralManagerDelegate,NSMenuDelegate,NSPopoverDelegate,WKNavigationDelegate,WKScriptMessageHandler>
@property NSTask *server;
@property NSWindow *window;
@property WKWebView *web;
@property CBCentralManager *bluetooth;
@property BOOL background;
@property NSStatusItem *statusItem;
@property NSMenu *deviceMenu;
@property NSDictionary *snapshot;
@property NSString *menuMessage;
@property NSDate *menuMessageUntil;
@property NSDictionary *noiseM,*intentM;
@property NSInteger changes,noiseTimer;
@property NSDate *noiseStart;
@property BOOL refreshWanted;
@property BOOL refreshing;
@property BOOL changing;
@property NSDictionary *pending;
@property NSString *switchText;
@property NSArray *busySlots;
@property NSPopover *popover;
@property WKWebView *popWeb;
@property NSDate *popoverClosed;
@property id escMonitor;
@property NSInteger popRetries;
@property NSInteger webRetries;

@end
@implementation App
- (void)applicationDidFinishLaunching:(NSNotification *)note {
 NSDictionary *info=[[NSBundle mainBundle] infoDictionary];
 self.noiseM=BoseIdle();self.intentM=BoseIdle();
 self.bluetooth=[[CBCentralManager alloc] initWithDelegate:self queue:nil options:@{CBCentralManagerOptionShowPowerAlertKey:@NO}];
 self.server=[[NSTask alloc] init];self.server.executableURL=[NSURL fileURLWithPath:info[@"BosePython"]];self.server.arguments=@[info[@"BoseController"],@"--config",info[@"BoseConfig"]];
 NSMutableDictionary *environment=[[[NSProcessInfo processInfo] environment] mutableCopy];environment[@"BOSE_PARENT_PID"]=[NSString stringWithFormat:@"%d",getpid()];self.server.environment=environment;
 self.server.terminationHandler=^(NSTask *task){dispatch_async(dispatch_get_main_queue(),^{[NSApp terminate:nil];});};
 NSString *dir=[info[@"BoseConfig"] stringByDeletingLastPathComponent];
 for(NSString *name in @[@"service.log",@"service-error.log"]){NSString *path=[dir stringByAppendingPathComponent:name];if(![[NSFileManager defaultManager] fileExistsAtPath:path])[[NSFileManager defaultManager] createFileAtPath:path contents:nil attributes:@{NSFilePosixPermissions:@0600}];}
 NSFileHandle *out=[NSFileHandle fileHandleForWritingAtPath:[dir stringByAppendingPathComponent:@"service.log"]];[out seekToEndOfFile];self.server.standardOutput=out;
 NSFileHandle *err=[NSFileHandle fileHandleForWritingAtPath:[dir stringByAppendingPathComponent:@"service-error.log"]];[err seekToEndOfFile];self.server.standardError=err;
 NSError *error=nil;if(![self.server launchAndReturnError:&error])NSLog(@"Could not start Bose helper: %@",error.localizedDescription);
 self.statusItem=[[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
 NSImage *icon=[NSImage imageWithSystemSymbolName:@"headphones" accessibilityDescription:@"Bose Connections"];icon.template=YES;self.statusItem.button.image=icon;self.statusItem.button.toolTip=@"Bose 700 connections";
 self.statusItem.button.target=self;self.statusItem.button.action=@selector(statusClicked:);[self.statusItem.button sendActionOn:NSEventMaskLeftMouseUp|NSEventMaskRightMouseUp];
 self.deviceMenu=[NSMenu new];self.deviceMenu.autoenablesItems=NO;self.deviceMenu.delegate=self;
 [self makePopover];
 NSData *cached=[NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:@"snapshot.json"]];
 if(cached)self.snapshot=[NSJSONSerialization JSONObjectWithData:cached options:0 error:nil];
 [self rebuildMenu];dispatch_after(dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC),dispatch_get_main_queue(),^{[self refreshMenu];});
 if(!self.background)[self showWindow];
}
- (NSMenuItem *)item:(NSString *)title selector:(SEL)selector data:(id)data {
 NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:title action:selector keyEquivalent:@""];item.target=self;item.representedObject=data;item.enabled=selector!=NULL;return item;
}
- (NSMenuItem *)sectionHeader:(NSString *)title {
 if(@available(macOS 14.0,*))return [NSMenuItem sectionHeaderWithTitle:title];
 return [self item:title selector:NULL data:nil];
}
- (NSString *)label:(NSDictionary *)device {
 NSDictionary *labels=@{@"pc":@"Desktop PC",@"phone":@"Android phone",@"mac":@"MacBook Pro"};
 for(NSString *role in self.snapshot[@"roles"])if([self.snapshot[@"roles"][role] isEqual:device[@"address"]])return labels[role]?:device[@"name"];
 return device[@"name"]?:device[@"address"];
}
- (BOOL)isReachable {return [self.snapshot[@"reachable"] boolValue];}
- (BOOL)isLive {return [self isReachable]&&![self.snapshot[@"cached"] boolValue];}
// Items stay clickable while work runs: a click then becomes the queued intent or the held noise value.
- (BOOL)canChange {return [self isLive]||self.changing||![self.noiseM[@"kind"] isEqual:@"idle"];}
- (BOOL)workRunning {return self.changing||[self.noiseM[@"kind"] isEqual:@"sending"];}
// A result line lives 8 s (success) or 30 s (error), the lifetimes of the Android tile's notes; any new input clears it.
- (void)say:(NSString *)text error:(BOOL)error {self.menuMessage=text.length?text:nil;self.menuMessageUntil=text.length?[NSDate dateWithTimeIntervalSinceNow:error?30:8]:nil;}
- (NSDictionary *)queuedIntent {return [self.intentM[@"kind"] isEqual:@"queued"]?self.intentM[@"intent"]:nil;}
// The noise value on screen: the newest input while one is pending, else the verified headset value.
- (NSDictionary *)shownNoise {
 NSDictionary *shown=BoseNoiseShown(self.noiseM);if(shown)return shown;
 NSDictionary *noise=self.snapshot[@"noise"];if(![noise isKindOfClass:[NSDictionary class]])return nil;
 return @{@"level":noise[@"level"]?:@0,@"enabled":@([noise[@"enabled"] boolValue])};
}
- (NSString *)clock:(id)epoch {
 if(![epoch isKindOfClass:[NSNumber class]])return nil;
 NSDateFormatter *f=[NSDateFormatter new];f.timeStyle=NSDateFormatterShortStyle;f.dateStyle=NSDateFormatterNoStyle;return [f stringFromDate:[NSDate dateWithTimeIntervalSince1970:[epoch doubleValue]]];
}
- (NSString *)headerTitle {
 NSMutableArray *parts=[NSMutableArray arrayWithObject:@"Bose 700"];
 id battery=self.snapshot[@"battery"];if([battery isKindOfClass:[NSNumber class]])[parts addObject:[NSString stringWithFormat:@"%d%%",[battery intValue]]];
 NSDictionary *noise=[self shownNoise];if(noise&&[noise[@"enabled"] boolValue])[parts addObject:[NSString stringWithFormat:@"ANC %d",[noise[@"level"] intValue]]];
 return [parts componentsJoinedByString:@" · "];
}
- (NSString *)stateLine {
 if(self.menuMessage&&[self.menuMessageUntil timeIntervalSinceNow]>0)return self.menuMessage;
 if(self.refreshWanted)return @"Refreshing after the change…";
 if(self.refreshing)return @"Refreshing…";
 if(!self.snapshot)return @"Unavailable";
 if([self.snapshot[@"cached"] boolValue]){NSString *t=[self clock:self.snapshot[@"observed"]];return t?[@"Last known · " stringByAppendingString:t]:@"Last known";}
 if(![self isReachable])return @"Unavailable";
 NSUInteger n=0;for(NSDictionary *d in self.snapshot[@"devices"]?:@[])if([d[@"connected"] boolValue])n++;
 return [NSString stringWithFormat:@"%lu of 2 connected",(unsigned long)n];
}
- (NSString *)titleFor:(NSDictionary *)device plain:(NSString *)plain {
 NSString *address=device[@"address"];
 if([self.pending[@"address"] isEqual:address])return [self.pending[@"action"] isEqual:@"disconnect"]?@"Disconnecting…":BosePending;
 if(self.pending[@"replace"]&&[self.pending[@"replace"] isEqual:address])return @"Disconnecting…";
 NSDictionary *q=[self queuedIntent];
 if([q[@"address"] isEqual:address]||[q[@"replace"] isEqual:address])return [q[@"action"] isEqual:@"disconnect"]||[q[@"replace"] isEqual:address]?@"Disconnects next":@"Connects next";
 return plain;
}
- (BOOL)isQueued:(NSString *)address {NSDictionary *q=[self queuedIntent];return q&&([q[@"address"] isEqual:address]||[q[@"replace"] isEqual:address]);}
- (void)rebuildMenu {
 [self.deviceMenu removeAllItems];
 self.statusItem.button.appearsDisabled=![self isReachable];self.statusItem.button.alphaValue=[self isReachable]?1.0:0.55;
 [self.deviceMenu addItem:[self item:[self headerTitle] selector:NULL data:nil]];
 [self.deviceMenu addItem:[self item:[self stateLine] selector:NULL data:nil]];
 BOOL can=[self canChange];
 NSDictionary *queued=[self queuedIntent];BOOL queuedHere=[queued[@"action"] isEqual:@"here"];
 if(queued)[self.deviceMenu addItem:[self item:@"Queued · cancel" selector:@selector(cancelQueued:) data:nil]];
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 NSMenuItem *use=[self item:self.switchText?:(queuedHere&&!queued[@"replace"]?@"Moves here next":@"Use on this Mac") selector:@selector(useHereClicked:) data:nil];if(queuedHere&&!queued[@"replace"])use.state=NSControlStateValueMixed;[self.deviceMenu addItem:use];
 for(NSDictionary *slot in self.busySlots){
  BOOL mine=queuedHere&&[queued[@"replace"] isEqual:slot[@"address"]];
  NSMenuItem *row=[self item:mine?@"Moves here next":[BoseReplace stringByReplacingOccurrencesOfString:@"{label}" withString:slot[@"label"]?:@"device"] selector:@selector(replaceClicked:) data:slot[@"address"]];if(mine)row.state=NSControlStateValueMixed;[self.deviceMenu addItem:row];
 }
 NSString *hereRole=self.snapshot[@"here"];NSDictionary *roleMap=self.snapshot[@"roles"];NSString *hereAddress=([hereRole isKindOfClass:[NSString class]]&&[roleMap isKindOfClass:[NSDictionary class]])?roleMap[hereRole]:nil;
 NSArray *devices=self.snapshot[@"devices"]?:@[];
 NSMutableArray *connected=[NSMutableArray new],*saved=[NSMutableArray new];
 for(NSDictionary *d in devices)[([d[@"connected"] boolValue]?connected:saved) addObject:d];
 if(connected.count){
  [self.deviceMenu addItem:[NSMenuItem separatorItem]];[self.deviceMenu addItem:[self sectionHeader:@"Connected"]];
  for(NSDictionary *d in connected){
   NSString *name=[self label:d];if(hereAddress&&[hereAddress isEqual:d[@"address"]])name=[name stringByAppendingString:@" — this Mac"];
   NSMenuItem *row=[self item:[self titleFor:d plain:name] selector:@selector(deviceClicked:) data:@{@"action":@"disconnect",@"address":d[@"address"]}];
   row.state=[self isQueued:d[@"address"]]?NSControlStateValueMixed:NSControlStateValueOn;row.enabled=can;[self.deviceMenu addItem:row];
  }
 }
 if(saved.count){
  [self.deviceMenu addItem:[NSMenuItem separatorItem]];[self.deviceMenu addItem:[self sectionHeader:@"Saved"]];
  for(NSDictionary *d in saved){
   NSDictionary *action=@{@"action":@"connect",@"address":d[@"address"]};
   NSMenuItem *row=[self item:[self titleFor:d plain:[self label:d]] selector:@selector(deviceClicked:) data:action];row.enabled=can;if([self isQueued:d[@"address"]])row.state=NSControlStateValueMixed;
   if(connected.count>=2){
    row.action=NULL;NSMenu *replace=[NSMenu new];replace.autoenablesItems=NO;
    for(NSDictionary *old in connected){NSMutableDictionary *a=[action mutableCopy];a[@"replace"]=old[@"address"];NSMenuItem *r=[self item:[BoseReplace stringByReplacingOccurrencesOfString:@"{label}" withString:[self label:old]] selector:@selector(deviceClicked:) data:a];r.enabled=can;[replace addItem:r];}
    row.submenu=replace;
   }
   [self.deviceMenu addItem:row];
  }
 }
 NSDictionary *noise=self.snapshot[@"noise"];
 if([noise isKindOfClass:[NSDictionary class]]){
  NSDictionary *shown=[self shownNoise];BOOL on=[shown[@"enabled"] boolValue];NSNumber *level=shown[@"level"]?:@0;
  [self.deviceMenu addItem:[NSMenuItem separatorItem]];
  NSString *kind=self.noiseM[@"kind"],*sectionTitle=@"Noise cancellation";
  if([kind isEqual:@"held"])sectionTitle=[NSString stringWithFormat:@"%@ · applies when the %@ ends",on?[NSString stringWithFormat:@"Level %d",[level intValue]]:@"Off",self.switchText?@"switch":@"change"];
  else if(![kind isEqual:@"idle"])sectionTitle=on?[NSString stringWithFormat:@"Setting level %d…",[level intValue]]:@"Turning off…";
  NSMenuItem *section=[self item:sectionTitle selector:NULL data:nil];section.enabled=can;
  NSMenu *levels=[NSMenu new];levels.autoenablesItems=NO;
  NSMenuItem *toggle=[self item:@"On" selector:@selector(deviceClicked:) data:@{@"action":@"noise",@"level":level,@"enabled":@(!on)}];toggle.state=on?NSControlStateValueOn:NSControlStateValueOff;toggle.enabled=can;[levels addItem:toggle];
  [levels addItem:[NSMenuItem separatorItem]];
  for(NSNumber *n in @[@0,@3,@5,@7,@10]){
   NSMenuItem *preset=[self item:[n stringValue] selector:@selector(deviceClicked:) data:@{@"action":@"noise",@"level":n,@"enabled":@YES}];
   preset.state=[level isEqual:n]?NSControlStateValueOn:NSControlStateValueOff;preset.enabled=can&&on;[levels addItem:preset];
  }
  section.submenu=levels;[self.deviceMenu addItem:section];
 }
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 [self.deviceMenu addItem:[self item:@"Refresh" selector:@selector(refreshClicked:) data:nil]];
 NSMenuItem *open=[self item:@"Open full window" selector:@selector(openDashboard:) data:nil];open.enabled=YES;[self.deviceMenu addItem:open];
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 NSMenuItem *quit=[[NSMenuItem alloc] initWithTitle:@"Quit" action:@selector(terminate:) keyEquivalent:@"q"];quit.target=NSApp;[self.deviceMenu addItem:quit];
}
- (void)request:(NSString *)path data:(NSDictionary *)data completion:(void (^)(NSDictionary *,NSString *))completion {
 NSMutableURLRequest *r=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:[@"http://127.0.0.1:8847" stringByAppendingString:path]]];r.timeoutInterval=data?160:40;
 if(data){r.HTTPMethod=@"POST";[r setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];r.HTTPBody=[NSJSONSerialization dataWithJSONObject:data options:0 error:nil];}
 [[[NSURLSession sharedSession] dataTaskWithRequest:r completionHandler:^(NSData *raw,NSURLResponse *response,NSError *error){
  id parsed=raw?[NSJSONSerialization JSONObjectWithData:raw options:0 error:nil]:nil;NSDictionary *json=[parsed isKindOfClass:[NSDictionary class]]?parsed:nil;
  NSString *failure=error.localizedDescription?:json[@"error"];if(!json&&!failure)failure=@"Controller unavailable";
  dispatch_async(dispatch_get_main_queue(),^{completion(json,failure);});
 }] resume];
}
- (void)refreshMenu {
 // Deferred while work runs: the read goes out when the scheduler reaches idle, so it cannot answer around a change.
 if([self workRunning]){self.refreshWanted=YES;[self rebuildMenu];return;}
 if(self.refreshing)return;self.refreshing=YES;NSInteger gen=self.changes;[self rebuildMenu];
 __block BOOL settled=NO;
 // A reply is dropped when a change started after the read was sent or work is still running: it could undo a verified result.
 [self request:@"/api/cached" data:nil completion:^(NSDictionary *json,NSString *error){
  if(!settled&&gen==self.changes&&![self workRunning]&&!error&&json[@"devices"]){self.snapshot=json;[self rebuildMenu];}
 }];
 [self request:@"/api/overview" data:nil completion:^(NSDictionary *json,NSString *error){
  settled=YES;self.refreshing=NO;
  if(gen!=self.changes||[self workRunning]){[self rebuildMenu];return;}
  if(error||!json){
   if(self.snapshot){NSMutableDictionary *old=[self.snapshot mutableCopy];old[@"cached"]=@YES;self.snapshot=old;}
   if(!self.snapshot)[self say:error error:YES];
  }else{self.snapshot=json;NSUInteger n=0;for(NSDictionary *d in json[@"devices"]?:@[])if([d[@"connected"] boolValue])n++;if(n<2)self.busySlots=nil;}
  [self rebuildMenu];
 }];
}
- (void)menuWillOpen:(NSMenu *)menu {[self refreshMenu];}
- (void)menuDidClose:(NSMenu *)menu {if(menu==self.deviceMenu)self.statusItem.menu=nil;}
- (void)makePopover {
 WKWebViewConfiguration *config=[WKWebViewConfiguration new];WeakScript *proxy=[WeakScript new];proxy.target=self;
 [config.userContentController addScriptMessageHandler:proxy name:@"boseSize"];[config.userContentController addScriptMessageHandler:proxy name:@"boseOpenWindow"];
 self.popWeb=[[WKWebView alloc] initWithFrame:NSMakeRect(0,0,380,480) configuration:config];self.popWeb.navigationDelegate=self;
 [self.popWeb setValue:@NO forKey:@"drawsBackground"];if(@available(macOS 12.0,*))self.popWeb.underPageBackgroundColor=[NSColor clearColor];
 NSViewController *controller=[NSViewController new];controller.view=self.popWeb;
 self.popover=[NSPopover new];self.popover.behavior=NSPopoverBehaviorTransient;self.popover.contentViewController=controller;self.popover.contentSize=NSMakeSize(380,480);self.popover.delegate=self;
 __weak App *weakSelf=self;
 self.escMonitor=[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown handler:^NSEvent *(NSEvent *event){
  App *me=weakSelf;if(event.keyCode==53&&me.popover.shown&&event.window==me.popWeb.window){[me.popover performClose:nil];return nil;}return event;
 }];
 [self loadWeb:self.popWeb];
}
- (void)loadWeb:(WKWebView *)web {[web loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:web==self.popWeb?BosePopoverURL:BoseURL]]];}
- (void)webView:(WKWebView *)web didFinishNavigation:(WKNavigation *)navigation {if(web==self.popWeb)self.popRetries=0;else self.webRetries=0;}
- (void)webView:(WKWebView *)web didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
 if([error.domain isEqual:NSURLErrorDomain]&&error.code==NSURLErrorCancelled)return;
 NSInteger tries=web==self.popWeb?++self.popRetries:++self.webRetries;if(tries>60)return;
 __weak WKWebView *weakWeb=web;dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{WKWebView *w=weakWeb;if(w)[self loadWeb:w];});
}
- (void)webViewWebContentProcessDidTerminate:(WKWebView *)web {[self loadWeb:web];}
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
 if([message.name isEqual:@"boseOpenWindow"]){[self openDashboard:nil];return;}
 if(![message.name isEqual:@"boseSize"]||![message.body isKindOfClass:[NSDictionary class]])return;
 id height=((NSDictionary *)message.body)[@"height"];if(![height isKindOfClass:[NSNumber class]])return;
 CGFloat h=MIN(720,MAX(320,ceil([height doubleValue])));if(fabs(self.popover.contentSize.height-h)<1)return;
 BOOL animates=self.popover.animates;self.popover.animates=NO;self.popover.contentSize=NSMakeSize(380,h);self.popover.animates=animates;
}
- (void)popoverDidClose:(NSNotification *)note {self.popoverClosed=[NSDate date];}
- (void)statusClicked:(id)sender {
 NSEvent *event=NSApp.currentEvent;
 if(event.type==NSEventTypeRightMouseUp||(event.modifierFlags&NSEventModifierFlagOption)){
  [self.popover performClose:nil];self.statusItem.menu=self.deviceMenu;[self.statusItem.button performClick:nil];return;
 }
 if(self.popover.shown){[self.popover performClose:nil];return;}
 if(self.popoverClosed&&-[self.popoverClosed timeIntervalSinceNow]<0.3)return;
 NSStatusBarButton *button=self.statusItem.button;
 [NSApp activateIgnoringOtherApps:YES];[self.popover showRelativeToRect:button.bounds ofView:button preferredEdge:NSRectEdgeMinY];
 [self.popWeb.window makeFirstResponder:self.popWeb];
}
- (void)refreshClicked:(id)sender {[self say:nil error:NO];[self rebuildMenu];[self refreshMenu];}
- (void)openDashboard:(id)sender {[self.popover performClose:nil];[self showWindow];}
- (NSString *)failureText:(NSDictionary *)json error:(NSString *)error {
 NSDictionary *texts=@{@"unreachable":BoseErrUnreachable,@"timeout":BoseErrTimeout,@"unverified":BoseErrUnverified,@"keep_one":BoseErrKeepOne,@"no_audio":BoseErrNoAudio,@"audio_not_moved":BoseErrAudioNotMoved,@"forgotten":BoseErrForgotten};
 NSString *key=json[@"error_key"];NSString *text=[key isKindOfClass:[NSString class]]?texts[key]:nil;
 if(!text&&[json[@"error_key"] isEqual:@"busy"])text=BoseBusy;
 if(!text)text=[error containsString:@"timed out"]?BoseErrTimeout:BoseErrUnreachable;
 return [text stringByAppendingString:BoseRetryHint];
}
// Every connection input goes through act: it runs at once when nothing else does, else it becomes the one queued intent
// (latest wins, the same click again cancels it) until the running work ends and pump releases it.
- (void)act:(NSDictionary *)intent {
 [self say:nil error:NO];
 if([self workRunning]){self.intentM=BoseIntents(self.intentM,@{@"type":@"hold",@"intent":intent});[self rebuildMenu];return;}
 self.intentM=BoseIntents(self.intentM,@{@"type":@"cancel"});
 [self runIntent:intent];
}
- (void)cancelQueued:(id)sender {[self say:nil error:NO];self.intentM=BoseIntents(self.intentM,@{@"type":@"cancel"});[self rebuildMenu];}
// The intent is checked against the verified snapshot first: it may be stale by the time it runs.
- (void)runIntent:(NSDictionary *)intent {
 NSDictionary *check=BoseReleaseCheck(intent,self.snapshot,[self isLive]);NSString *decision=check[@"decision"];
 if([decision isEqual:@"run"]){if([intent[@"action"] isEqual:@"here"])[self switchHere:intent[@"replace"]];else [self performNow:check[@"body"]];return;}
 NSString *name=intent[@"address"];for(NSDictionary *d in self.snapshot[@"devices"])if([d[@"address"] isEqual:intent[@"address"]])name=[self label:d];
 if([decision isEqual:@"already-disconnected"])[self say:[name stringByAppendingString:@" is already disconnected."] error:NO];
 else if([decision isEqual:@"already-connected"])[self say:[name stringByAppendingString:@" is already connected."] error:NO];
 else if([decision isEqual:@"busy"])[self say:BoseBusy error:YES];
 else [self say:[NSString stringWithFormat:@"%@ not sent: the headphones aren’t reachable now",[intent[@"action"] isEqual:@"connect"]?@"Connect":@"Disconnect"] error:YES];
 [self rebuildMenu];
}
// The one scheduler: called whenever work ends or input arrives (machines: BoseSchedule, BoseIntents, BoseNoiser).
- (void)pump {
 for(int n=0;n<4;n++){
  NSString *d=BoseSchedule(self.changing,self.noiseM,self.intentM,[self isLive]);
  if([d isEqual:@"hold-noise"]){self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"hold"});self.noiseTimer++;[self rebuildMenu];return;}
  if([d isEqual:@"resume-noise"]){self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"resume"});continue;}
  if([d isEqual:@"drop-noise"]){self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"drop"});[self say:BoseNoiseDropped error:YES];[self rebuildMenu];return;}
  if([d isEqual:@"intent"]){NSDictionary *i=[self queuedIntent];self.intentM=BoseIntents(self.intentM,@{@"type":@"release"});[self runIntent:i];if([self workRunning])return;continue;}
  if([d isEqual:@"noise"])[self pumpNoise];
  if([d isEqual:@"idle"]&&self.refreshWanted){self.refreshWanted=NO;[self refreshMenu];}
  return;
 }
}
- (void)noiseInput:(NSDictionary *)value {
 if(![self isLive]&&!self.changing){[self say:BoseNoiseDropped error:YES];[self rebuildMenu];return;}
 self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"input",@"value":value});[self say:nil error:NO];[self pump];[self rebuildMenu];
}
// One noise write at a time, 250 ms between starts, the newest value always the one sent.
- (void)pumpNoise {
 if(![self.noiseM[@"kind"] isEqual:@"waiting"]||self.changing)return;
 NSTimeInterval wait=self.noiseStart?0.25+[self.noiseStart timeIntervalSinceNow]:0;
 if(wait>0){NSInteger token=++self.noiseTimer;dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)(wait*NSEC_PER_SEC)),dispatch_get_main_queue(),^{if(token==self.noiseTimer)[self pump];});return;}
 NSDictionary *value=self.noiseM[@"queued"],*verified=self.snapshot[@"noise"];
 self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"send"});
 BOOL same=[verified isKindOfClass:[NSDictionary class]]&&[verified[@"enabled"] boolValue]==[value[@"enabled"] boolValue]&&(![value[@"enabled"] boolValue]||[verified[@"level"] isEqual:value[@"level"]]);
 if(same){self.noiseM=BoseNoiser(self.noiseM,@{@"type":@"ok"});[self rebuildMenu];[self pump];return;}
 self.noiseStart=[NSDate date];self.changes++;[self rebuildMenu];
 [self request:@"/api/override" data:@{@"action":@"noise",@"level":value[@"level"],@"enabled":value[@"enabled"]} completion:^(NSDictionary *json,NSString *error){
  NSDictionary *state=[json[@"state"] isKindOfClass:[NSDictionary class]]?json[@"state"]:nil;
  if(state&&self.snapshot&&![state[@"devices"] count]){NSMutableDictionary *merged=[self.snapshot mutableCopy];if(state[@"noise"])merged[@"noise"]=state[@"noise"];if(state[@"battery"]&&state[@"battery"]!=[NSNull null])merged[@"battery"]=state[@"battery"];self.snapshot=merged;}
  else if(state)self.snapshot=state;
  self.changes++;BOOL ok=!error&&[json[@"ok"] boolValue]&&[json[@"verified"] boolValue];
  if(!ok)[self say:[self failureText:json error:error] error:YES];
  else if(!BoseValue(self.noiseM,@"queued"))[self say:@"Noise cancellation updated" error:NO];
  self.noiseM=BoseNoiser(self.noiseM,@{@"type":ok?@"ok":@"fail"});
  [self rebuildMenu];
  [self pump];
  if(!state&&!error&&![self workRunning])[self refreshMenu];
 }];
}
- (void)switchHere:(NSString *)replace {
 NSString *label=nil;for(NSDictionary *slot in self.busySlots)if(replace&&[slot[@"address"] isEqual:replace])label=slot[@"label"];
 NSMutableDictionary *body=[@{@"source":@"mac-menu",@"request_id":[[[NSUUID UUID].UUIDString substringToIndex:8] lowercaseString]} mutableCopy];if(replace)body[@"replace"]=replace;
 self.changing=YES;self.changes++;self.busySlots=nil;self.switchText=label?[BoseReplacing stringByReplacingOccurrencesOfString:@"{label}" withString:label]:BosePending;[self rebuildMenu];[self pump];
 [self request:@"/api/switch" data:body completion:^(NSDictionary *json,NSString *error){
  self.changing=NO;self.changes++;self.switchText=nil;
  NSDictionary *state=[json[@"state"] isKindOfClass:[NSDictionary class]]?json[@"state"]:nil;
  if(state)self.snapshot=state;
  if([json[@"ok"] boolValue]&&[json[@"verified"] boolValue])[self say:BoseOk error:NO];
  else if([json[@"busy"] boolValue]){[self say:BoseBusy error:YES];self.busySlots=[json[@"slots"] isKindOfClass:[NSArray class]]?json[@"slots"]:nil;}
  else [self say:[self failureText:json error:error] error:YES];
  [self rebuildMenu];
  [self pump];
  if(!state&&![json[@"busy"] boolValue]&&![self workRunning])[self refreshMenu];
 }];
}
- (void)useHereClicked:(NSMenuItem *)sender {[self act:@{@"action":@"here"}];}
- (void)replaceClicked:(NSMenuItem *)sender {[self act:@{@"action":@"here",@"replace":sender.representedObject}];}
- (void)deviceClicked:(NSMenuItem *)sender {
 NSDictionary *data=[sender.representedObject copy];
 if([data[@"action"] isEqual:@"noise"])[self noiseInput:@{@"level":data[@"level"],@"enabled":data[@"enabled"]}];
 else [self act:data];
}
- (void)performNow:(NSDictionary *)data {
 self.changing=YES;self.changes++;self.pending=data;[self rebuildMenu];[self pump];
 [self request:@"/api/override" data:data completion:^(NSDictionary *json,NSString *error){
  self.changing=NO;self.changes++;self.pending=nil;
  NSDictionary *state=[json[@"state"] isKindOfClass:[NSDictionary class]]?json[@"state"]:nil;
  if(state)self.snapshot=state;
  if(error||![json[@"ok"] boolValue]||![json[@"verified"] boolValue])[self say:[self failureText:json error:error] error:YES];
  [self rebuildMenu];
  [self pump];
  if(!state&&!error&&![self workRunning])[self refreshMenu];
 }];
}
- (void)centralManagerDidUpdateState:(CBCentralManager *)central {}
- (void)showWindow {
 if(!self.window){self.window=[[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,420,780) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable|NSWindowStyleMaskMiniaturizable|NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];self.window.title=@"Bose Connections";self.web=[[WKWebView alloc] initWithFrame:self.window.contentView.bounds];self.web.navigationDelegate=self;self.web.autoresizingMask=NSViewWidthSizable|NSViewHeightSizable;self.window.contentView=self.web;self.window.contentMinSize=NSMakeSize(360,480);self.window.releasedWhenClosed=NO;[self.window center];[self loadWeb:self.web];}
 [self.window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)flag {[self showWindow];return YES;}
- (void)applicationWillTerminate:(NSNotification *)note {if(self.server.running)[self.server terminate];}
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app {return NO;}
@end
int main(int argc,const char *argv[]){@autoreleasepool{NSApplication *app=[NSApplication sharedApplication];[app setActivationPolicy:NSApplicationActivationPolicyAccessory];App *delegate=[App new];delegate.background=argc>1&&strcmp(argv[1],"--background")==0;app.delegate=delegate;[app run];}return 0;}
