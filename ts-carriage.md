# AV1 specification for TS

Jean Baptiste Kempf (jb@videolan.org)  
Kieran Kunhya (kierank@obe.tv)  
Adrien Maglo (adrien@videolabs.io)  
Christophe Massiot (cmassiot@openheadend.tv)  
Mathieu Monnier (m.monnier@ateme.com)  
Mickael Raulet (m.raulet@ateme.com)

ATEME, OpenHeadend, Open Broadcast Systems, Videolabs, Videolan

DVB meeting 11/12 dec 2018<

## TODO today

* Identifier
* Descriptor
* Buffer Size and Rate mbn
* TU, OBU
* How to pack/StartCode emulation
* RAP
* Signal HRD (incomplete need SEI?)
* DTS on frames that are not shown
* Wording around unifying the model between AV1 and TS
* Signal UHD? (for HW decoders with limited capabilities like several hw decoding chips but only one able to decode UHD) - done in the level

## Identifier

'AV1 ' <A-V-1-space>

## Descriptor

Need to register format_identifier (SMPTE) *and* EN 300 468 Private data specifier descriptor

https://smpte-ra.org/mpeg-ts-ids


### Registration descriptor

descriptor_tag = 8  
descriptor_length = 8  
AV-1 --> FIXME you decide  

### AV1_Descriptor

Need to use DVB private data specifier descriptor beforehands, with a private data specifier registered from https://www.dvbservices.com/identifiers/private_data_spec_id.  
Requested 07-12-2018

```
descriptor_tag = 8
descriptor_length = 8

seq_profile = 3
seq_level_idx[ i ] --- f(5)
if ( seq_level_idx[ i ] > 7 ) { 
        seq_tier[ i ] --- f(1)
} else {
        seq_tier[ i ] = 0
}
high_bitdepth --- f(1)
if ( seq_profile == 2 && high_bitdepth ) {
        twelve_bit --- f(1)
        BitDepth = twelve_bit ? 12 : 10
} else if ( seq_profile <= 2 ) {
        BitDepth = high_bitdepth ? 10 : 8
}
/*
if ( seq_profile == 1 ) {
        mono_chrome = 0
} else {
        mono_chrome --- f(1)
}*/

unsigned int (3) seq_profile
unsigned int (5) seq_level_idx_0

unsigned int (1) seq_tier_0
unsigned int (1) high_bitdepth
unsigned int (1) twelve_bit
unsigned int (1) monochrome
unsigned int (1) chroma_subsampling_x
unsigned int (1) chroma_subsampling_y
unsigned int (2) chroma_sample_position

HDR_WCG_idc {0, 1, 2, 3} FIXME is this ok

unsigned int (8) reserved = 11111111
```

## Buffer Models

Diagram similar to T-REC-H.222.0-201703-S!!PDF-E.pdf 2.17.2

The following additional notations are used to describe the T-STD extensions and are illustrated in Figure 2-18.  
t(i) indicates the time in seconds at which the i-th byte of the transport stream enters the system target decoder  
TBn is the transport buffer for elementary stream n  
TBS is the size of the transport buffer TBn, measured in bytes  
MBn is the multiplexing buffer for elementary stream n  
MBSn is the size of the multiplexing buffer MBn, measured in bytes  
EBn is the elementary stream buffer for the AV1 video stream  
EBSn is the size of the multiplexing buffer MBn, measured in bytes  
j is an index to the AV1 Decodable Frame Group of the AV1 video stream  
An(j) is the j-th Decodable Frame Group of the AV1 video bitstream  
tdn (j) is the decoding time of An(j), measured in seconds, in the system target decoder  
Rxn is the transfer rate from the transport buffer TBn to the multiplex buffer MBn as specified below.  
Rbxn is the transfer rate from the multiplex buffer MBn to the elementary stream buffer EBn as specified below  

TBn is fixed to 512 bytes

(Do units match here?) some clause explaining this?

MBSn = BSmux + BSoh + 0.1 × BufferSize  
where BSoh, packet overhead buffering, is defined as:  
BSoh = (1/750) seconds × max{ 1100 × BitRate, 2 000 000 bit/s}  
and BSmux, additional multiplex buffering, is defined as:  
BSmux = 0.004 seconds ×max{ 1100 × BitRate, 2 000 000 bit/s}  

where BufferSize and BitRate are defined in Annex E of the AV1 Bitstream & Decoding Process Specification

There is exactly one elementary stream buffer EBn for all the elementary streams in the set of received elementary streams associated by hierarchy descriptors, with a total size EBSn  
EBSn = BufferSize


Transfer from TBn to MBn is applied as follows:  
When there is no data in TBn then Rxn is equal to zero. Otherwise:  
Rxn = 1.1 * BitRate

The leak method shall be used to transfer data from MBn to EBn as follows:  
Rbxn = 1.1 × BitRate

If there is PES packet payload data in MBn, and buffer EBn is not full, the PES packet payload is transferred from MBn to EBn at a rate equal to Rbxn. If EBn is full, data are not removed from MBn. When a byte of data is transferred from MBn to EBn, all PES packet header bytes that are in MBn and precede that byte are instantaneously removed and discarded. When there is no PES packet payload data present in MBn, no data is removed from MBn. All data that enters MBn leaves it. All PES packet payload data bytes enter EBn instantaneously upon leaving MBn.

### STD delay

The STD delay of any AV1 video through the system target decoders buffers TBn, MBn, and EBn shall be constrained by tdn(j) – t(i) ≤ 10 seconds for all j, and all bytes i in access unit An(j).

### Buffer management conditions

Transport streams shall be constructed so that the following conditions for buffer management are satisfied:  
ISO/IEC 13818-1:2018 (E)  
Rec. ITU-T H.222.0 (03/2017) 185  
* Each TBn shall not overflow and shall be empty at least once every second.
* Each MBn, EBn and DPB shall not overflow.
* EBn shall not underflow, except when the Operating parameters info syntax has low_delay_mode_flag set to '1'. Underflow of EBn occurs for AV1 access unit An(j) when one or more bytes of An(j) are not present in EBn at the decoding time tdn(j).

## Decodable Frame Group

The equivalent of Access Unit for HEVC and H.264

An AV1 Access Unit is defined as a Decodable Frame Group as defined in the AV1 Bitstream & Decoding Process Specification Annex E

## Carriage in PES packets 

The PES flag data_alignment_indicator SHALL be set to 1 on PES packets carrying a Random Access Point access unit.

AV1 access units are carried in PES packets as PES_packet_data_bytes, using private_stream_1 as defined in Table 2-22 of H.222.  
TS 101 154 : Usage of multiple pictures per PES packet as per the above represents a very constrained set of conditions under which this may occur. Use of this feature potentially introduces complexity in timing extraction. Therefore, it is recommended that this feature is only used where the consequential bitrate savings are essential and the potential system effects are considered.

(FIXME: semantics behind a frame being decoded BUT not shown)

For synchronization and STD management, PTSs and, when appropriate, DTSs are encoded in the header of the PES packet that carries the AV1 video elementary stream data. For PTS and DTS encoding, the constraints and semantics apply as defined in 2.4.3.7 and 2.7.

## Definition of DTS and PTS

### PTS

If a PTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the PTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the PresentationTime in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

### DTS

If a DTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the DTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the ScheduledRemovalTiming in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

## Administrativia

* finish by Tuesday night, for DVB
* Descriptor registration, format_identifier,
* code.videolan.org -> github.com/videolan/
* RFC first, then maybe ETSI standardisation




