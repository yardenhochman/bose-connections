#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
#import <CoreBluetooth/CoreBluetooth.h>
static NSString *const BoseURL=@"http://127.0.0.1:8847/",*const BosePopoverURL=@"http://127.0.0.1:8847/?view=popover";
// Texts of tests/switch-contract.json (checked verbatim by tests/test_mac_contract.py).
static NSString *const BosePending=@"Connecting…",*const BoseReplacing=@"Replacing {label}…",*const BoseOk=@"Playing on Bose 700",*const BoseBusy=@"Both slots busy · choose one to replace",*const BoseReplace=@"Replace {label}",*const BoseRetryHint=@" · tap to retry";
static NSString *const BoseErrUnreachable=@"Couldn’t reach the headphones",*const BoseErrTimeout=@"Took too long to switch",*const BoseErrUnverified=@"The headphones didn’t confirm the switch",*const BoseErrKeepOne=@"Can’t replace that one: keep a phone, PC or Mac connected",*const BoseErrNoAudio=@"Connected, but no sound from the headphones",*const BoseErrAudioNotMoved=@"Headphones connected, but PC audio didn’t switch";
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
 NSMenuItem *item=[[NSMenuItem alloc] initWithTitle:title action:selector keyEquivalent:@""];item.target=self;item.representedObject=data;item.enabled=selector!=NULL && !self.changing;return item;
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
- (BOOL)canChange {return [self isReachable]&&![self.snapshot[@"cached"] boolValue]&&!self.changing;}
- (NSString *)clock:(id)epoch {
 if(![epoch isKindOfClass:[NSNumber class]])return nil;
 NSDateFormatter *f=[NSDateFormatter new];f.timeStyle=NSDateFormatterShortStyle;f.dateStyle=NSDateFormatterNoStyle;return [f stringFromDate:[NSDate dateWithTimeIntervalSince1970:[epoch doubleValue]]];
}
- (NSString *)headerTitle {
 NSMutableArray *parts=[NSMutableArray arrayWithObject:@"Bose 700"];
 id battery=self.snapshot[@"battery"];if([battery isKindOfClass:[NSNumber class]])[parts addObject:[NSString stringWithFormat:@"%d%%",[battery intValue]]];
 NSDictionary *noise=self.snapshot[@"noise"];if([noise isKindOfClass:[NSDictionary class]]&&[noise[@"enabled"] boolValue]&&noise[@"level"])[parts addObject:[NSString stringWithFormat:@"ANC %d",[noise[@"level"] intValue]]];
 return [parts componentsJoinedByString:@" · "];
}
- (NSString *)stateLine {
 if(self.menuMessage)return self.menuMessage;
 if(!self.snapshot)return self.refreshing?@"Refreshing…":@"Unavailable";
 if([self.snapshot[@"cached"] boolValue]){NSString *t=[self clock:self.snapshot[@"observed"]];return t?[@"Last known · " stringByAppendingString:t]:@"Last known";}
 if(![self isReachable])return @"Unavailable";
 NSUInteger n=0;for(NSDictionary *d in self.snapshot[@"devices"]?:@[])if([d[@"connected"] boolValue])n++;
 return [NSString stringWithFormat:@"%lu of 2 connected",(unsigned long)n];
}
- (NSString *)titleFor:(NSDictionary *)device plain:(NSString *)plain {
 NSString *address=device[@"address"];
 if([self.pending[@"address"] isEqual:address])return [self.pending[@"action"] isEqual:@"disconnect"]?@"Disconnecting…":BosePending;
 if(self.pending[@"replace"]&&[self.pending[@"replace"] isEqual:address])return @"Disconnecting…";
 return plain;
}
- (void)rebuildMenu {
 [self.deviceMenu removeAllItems];
 self.statusItem.button.appearsDisabled=![self isReachable];self.statusItem.button.alphaValue=[self isReachable]?1.0:0.55;
 [self.deviceMenu addItem:[self item:[self headerTitle] selector:NULL data:nil]];
 [self.deviceMenu addItem:[self item:[self stateLine] selector:NULL data:nil]];
 BOOL can=[self canChange];
 [self.deviceMenu addItem:[NSMenuItem separatorItem]];
 NSMenuItem *use=[self item:self.switchText?:@"Use on this Mac" selector:@selector(useHereClicked:) data:nil];use.enabled=!self.changing;[self.deviceMenu addItem:use];
 for(NSDictionary *slot in self.busySlots){
  NSMenuItem *row=[self item:[BoseReplace stringByReplacingOccurrencesOfString:@"{label}" withString:slot[@"label"]?:@"device"] selector:@selector(replaceClicked:) data:slot[@"address"]];row.enabled=!self.changing;[self.deviceMenu addItem:row];
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
   row.state=NSControlStateValueOn;row.enabled=can;[self.deviceMenu addItem:row];
  }
 }
 if(saved.count){
  [self.deviceMenu addItem:[NSMenuItem separatorItem]];[self.deviceMenu addItem:[self sectionHeader:@"Saved"]];
  for(NSDictionary *d in saved){
   NSDictionary *action=@{@"action":@"connect",@"address":d[@"address"]};
   NSMenuItem *row=[self item:[self titleFor:d plain:[self label:d]] selector:@selector(deviceClicked:) data:action];row.enabled=can;
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
  BOOL on=[noise[@"enabled"] boolValue];NSNumber *level=noise[@"level"]?:@0;
  [self.deviceMenu addItem:[NSMenuItem separatorItem]];
  NSMenuItem *section=[self item:[self.pending[@"action"] isEqual:@"noise"]?@"Setting noise…":@"Noise cancellation" selector:NULL data:nil];section.enabled=can||[self.pending[@"action"] isEqual:@"noise"];
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
 if(self.refreshing||self.changing)return;self.refreshing=YES;
 __block BOOL settled=NO;
 [self request:@"/api/cached" data:nil completion:^(NSDictionary *json,NSString *error){
  if(!settled&&!self.changing&&!error&&json[@"devices"]){self.snapshot=json;[self rebuildMenu];}
 }];
 [self request:@"/api/overview" data:nil completion:^(NSDictionary *json,NSString *error){
  settled=YES;self.refreshing=NO;if(self.changing)return;
  if(error||!json){
   if(self.snapshot){NSMutableDictionary *old=[self.snapshot mutableCopy];old[@"cached"]=@YES;self.snapshot=old;}
   self.menuMessage=self.snapshot?nil:error;
  }else{self.snapshot=json;self.menuMessage=nil;NSUInteger n=0;for(NSDictionary *d in json[@"devices"]?:@[])if([d[@"connected"] boolValue])n++;if(n<2)self.busySlots=nil;}
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
- (void)refreshClicked:(id)sender {[self refreshMenu];}
- (void)openDashboard:(id)sender {[self.popover performClose:nil];[self showWindow];}
- (NSString *)failureText:(NSDictionary *)json error:(NSString *)error {
 NSDictionary *texts=@{@"unreachable":BoseErrUnreachable,@"timeout":BoseErrTimeout,@"unverified":BoseErrUnverified,@"keep_one":BoseErrKeepOne,@"no_audio":BoseErrNoAudio,@"audio_not_moved":BoseErrAudioNotMoved};
 NSString *key=json[@"error_key"];NSString *text=[key isKindOfClass:[NSString class]]?texts[key]:nil;
 if(!text&&[json[@"error_key"] isEqual:@"busy"])text=BoseBusy;
 if(!text)text=[error containsString:@"timed out"]?BoseErrTimeout:BoseErrUnreachable;
 return [text stringByAppendingString:BoseRetryHint];
}
- (void)switchHere:(NSString *)replace {
 if(self.changing)return;
 NSString *label=nil;for(NSDictionary *slot in self.busySlots)if(replace&&[slot[@"address"] isEqual:replace])label=slot[@"label"];
 NSMutableDictionary *body=[@{@"source":@"mac-menu",@"request_id":[[[NSUUID UUID].UUIDString substringToIndex:8] lowercaseString]} mutableCopy];if(replace)body[@"replace"]=replace;
 self.changing=YES;self.menuMessage=nil;self.busySlots=nil;self.switchText=label?[BoseReplacing stringByReplacingOccurrencesOfString:@"{label}" withString:label]:BosePending;[self rebuildMenu];
 [self request:@"/api/switch" data:body completion:^(NSDictionary *json,NSString *error){
  self.changing=NO;self.switchText=nil;
  NSDictionary *state=[json[@"state"] isKindOfClass:[NSDictionary class]]?json[@"state"]:nil;
  if(state)self.snapshot=state;
  if([json[@"ok"] boolValue]&&[json[@"verified"] boolValue])self.menuMessage=BoseOk;
  else if([json[@"busy"] boolValue]){self.menuMessage=BoseBusy;self.busySlots=[json[@"slots"] isKindOfClass:[NSArray class]]?json[@"slots"]:nil;}
  else self.menuMessage=[self failureText:json error:error];
  [self rebuildMenu];
  if(!state&&![json[@"busy"] boolValue])[self refreshMenu];
 }];
}
- (void)useHereClicked:(NSMenuItem *)sender {[self switchHere:nil];}
- (void)replaceClicked:(NSMenuItem *)sender {[self switchHere:sender.representedObject];}
- (void)deviceClicked:(NSMenuItem *)sender {
 if(self.changing)return;NSDictionary *data=[sender.representedObject copy];self.changing=YES;self.pending=data;self.menuMessage=nil;[self rebuildMenu];
 [self request:@"/api/override" data:data completion:^(NSDictionary *json,NSString *error){
  self.changing=NO;self.pending=nil;
  NSDictionary *state=[json[@"state"] isKindOfClass:[NSDictionary class]]?json[@"state"]:nil;
  if(state&&[data[@"action"] isEqual:@"noise"]&&self.snapshot&&![state[@"devices"] count]){NSMutableDictionary *merged=[self.snapshot mutableCopy];if(state[@"noise"])merged[@"noise"]=state[@"noise"];if(state[@"battery"]&&state[@"battery"]!=[NSNull null])merged[@"battery"]=state[@"battery"];self.snapshot=merged;}
  else if(state)self.snapshot=state;
  if(error||![json[@"ok"] boolValue]||![json[@"verified"] boolValue])self.menuMessage=[self failureText:json error:error];
  else self.menuMessage=nil;
  [self rebuildMenu];
  if(!state&&!error)[self refreshMenu];
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
