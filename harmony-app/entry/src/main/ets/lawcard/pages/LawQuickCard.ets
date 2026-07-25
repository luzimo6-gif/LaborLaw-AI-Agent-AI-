let cardStorage: LocalStorage = new LocalStorage();

@Entry(cardStorage)
@Component
struct LawQuickCard {
  @LocalStorageProp('documentCount') documentCount: number = 2790;
  @LocalStorageProp('searchableDocumentCount') searchableDocumentCount: number = 2761;
  @LocalStorageProp('statusText') statusText: string = '本地资料已就绪';
  @LocalStorageProp('recentConsultation') recentConsultation: string = '尚无咨询';

  readonly actionType: string = 'router';
  readonly abilityName: string = 'EntryAbility';

  @Builder
  private QuickEntry(label: string, scenario: string, tint: string, accent: string) {
    Row() {
      Text(label)
        .fontSize(11)
        .fontWeight(FontWeight.Medium)
        .fontColor(accent)
        .width('100%')
        .textAlign(TextAlign.Center)
        .maxLines(1)
    }
    .width('100%')
    .height(36)
    .padding({ left: 5, right: 5 })
    .backgroundColor(tint)
    .borderRadius(11)
    .onClick(() => {
      postCardAction(this, {
        action: this.actionType,
        abilityName: this.abilityName,
        params: {
          source: 'law_quick_card',
          scenario: scenario
        }
      });
    })
  }

  build() {
    Column() {
      Row() {
        Column() {
          Text('劳动法助手')
            .fontSize(14)
            .fontWeight(FontWeight.Bold)
            .fontColor('#20333A')
            .maxLines(1)
          Text('AI 权益速查 · ' + this.documentCount.toString() + ' 份')
            .fontSize(8)
            .fontColor('#6D7977')
            .margin({ top: 2 })
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Text(this.statusText === '本地资料已就绪' ? '本地就绪' : this.statusText)
          .fontSize(8)
          .fontColor('#3F817C')
          .padding({ left: 6, right: 6, top: 4, bottom: 4 })
          .backgroundColor('#E3F1EC')
          .borderRadius(8)
          .maxLines(1)
      }
      .width('100%')

      Row({ space: 7 }) {
        Column({ space: 7 }) {
          this.QuickEntry('欠薪', 'wage_arrears', '#FFF0E3', '#B95735')
          this.QuickEntry('违法解除', 'illegal_termination', '#FFF0E3', '#B95735')
        }
        .layoutWeight(1)
        Column({ space: 7 }) {
          this.QuickEntry('未签合同', 'unsigned_contract', '#E9F2EF', '#2F716C')
          this.QuickEntry('加班', 'overtime', '#E9F2EF', '#2F716C')
        }
        .layoutWeight(1)
      }
      .width('100%')
      .margin({ top: 10 })

      Blank()

      Row() {
        Text(this.searchableDocumentCount.toString() + ' 份可检索')
          .fontSize(8)
          .fontColor('#3F817C')
          .maxLines(1)
        Blank()
        Text('最近 ' + this.recentConsultation)
          .fontSize(8)
          .fontColor('#6D7977')
          .maxLines(1)
      }
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .padding(13)
    .backgroundColor('#FBF7EF')
    .borderRadius(22)
  }
}
